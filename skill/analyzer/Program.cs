using System.Collections.Concurrent;
using System.Diagnostics;

namespace CsharpDependencyGraph;

public static class Program
{
    public static int Main(string[] args)
    {
        var opt = new AnalyzerOptions();
        var outPath = "";
        var excludeExtra = new List<string>();
        var quiet = false;

        for (var i = 0; i < args.Length; i++)
        {
            switch (args[i])
            {
                case "--root": opt.Root = Path.GetFullPath(args[++i]); break;
                case "--out": outPath = args[++i]; break;
                case "--exclude": excludeExtra.AddRange(args[++i].Split(',', StringSplitOptions.RemoveEmptyEntries)); break;
                case "--no-decl-refs": opt.DeclarationTypeRefs = false; break;
                case "--no-access-edges": opt.AccessEdges = false; break;
                case "--max-files": opt.MaxFiles = int.Parse(args[++i]); break;
                case "--quiet": quiet = true; break;
                case "--help":
                case "-h":
                    Console.WriteLine("使い方: cgd --root <repo> --out <graph.csharp.json> [--exclude a,b] [--no-decl-refs] [--no-access-edges] [--max-files N]");
                    return 0;
                default:
                    Console.Error.WriteLine($"不明な引数: {args[i]}");
                    return 2;
            }
        }

        if (string.IsNullOrEmpty(opt.Root) || !Directory.Exists(opt.Root))
        {
            Console.Error.WriteLine("--root にディレクトリを指定してください。");
            return 2;
        }
        if (string.IsNullOrEmpty(outPath))
        {
            Console.Error.WriteLine("--out を指定してください。");
            return 2;
        }
        foreach (var extra in excludeExtra) opt.ExcludeDirs.Add(extra);

        var stopwatch = Stopwatch.StartNew();
        var files = EnumerateFiles(opt);
        if (opt.MaxFiles > 0 && files.Count > opt.MaxFiles) files = files.GetRange(0, opt.MaxFiles);
        if (!quiet) Console.Error.WriteLine($"[csharp] 対象 .cs ファイル: {files.Count} 件");

        // ---- 1 周目: 宣言収集
        var results = new FileResult[files.Count];
        var options = new ParallelOptions { MaxDegreeOfParallelism = Environment.ProcessorCount };
        Parallel.For(0, files.Count, options, index =>
        {
            var rel = ToRelative(opt.Root, files[index]);
            results[index] = DeclarationScanner.ScanFile(files[index], rel);
        });

        var index = new TypeIndex();
        foreach (var result in results) index.Ingest(result);
        if (!quiet) Console.Error.WriteLine($"[csharp] 型 {index.ByQualified.Count} 件 / partial 統合 {index.MergedPartials} 件（{stopwatch.ElapsedMilliseconds} ms）");

        // ---- 2 周目: 参照解決
        var scanner = new ReferenceScanner(opt, index);
        Parallel.For(0, files.Count, options, i => scanner.ScanFile(files[i], results[i]));
        if (!quiet) Console.Error.WriteLine($"[csharp] エッジ {scanner.Edges.Count} 件 / 未解決呼び出し {scanner.UnresolvedCount} 件（{stopwatch.ElapsedMilliseconds} ms）");

        // ---- 出力
        var fragment = new GraphFragment
        {
            Root = opt.Root,
            GeneratedAt = DateTimeOffset.UtcNow.ToString("yyyy-MM-ddTHH:mm:sszzz"),
            Producer = "csharp-analyzer",
        };
        AddNodes(fragment, index, results);
        // 2 周目は Parallel.For なので辞書の挿入順（＝列挙順）はスレッド順序に左右される。
        // 同じ入力なら同じバイト列が出るよう、エッジは ID の順序で書き出す
        foreach (var edge in scanner.Edges.Values.OrderBy(e => e.Id, StringComparer.Ordinal)) fragment.Edges.Add(edge);

        var byKind = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var edge in scanner.Edges.Values)
        {
            byKind.TryGetValue(edge.Kind, out var n);
            byKind[edge.Kind] = n + 1;
        }
        var memberCount = 0;
        foreach (var type in index.ByQualified.Values) memberCount += type.MembersByName.Count;
        fragment.Stats["csharpFiles"] = files.Count;
        fragment.Stats["csharpParseFailures"] = results.Count(r => r.ParseFailed);
        fragment.Stats["csharpTypes"] = index.ByQualified.Count;
        fragment.Stats["csharpMembers"] = memberCount;
        fragment.Stats["csharpEdges"] = scanner.Edges.Count;
        fragment.Stats["csharpUnresolvedCalls"] = scanner.UnresolvedCount;
        fragment.Stats["csharpRejectedTypeFiles"] = results.Count(r => r.RejectedTypes.Count > 0);
        fragment.Stats["csharpRejectedTypes"] = results.Sum(r => r.RejectedTypes.Count);
        foreach (var kv in byKind.OrderBy(k => k.Key, StringComparer.Ordinal)) fragment.Stats["csharpEdge_" + kv.Key] = kv.Value;

        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath))!);
        File.WriteAllText(Path.GetFullPath(outPath), fragment.ToJson());
        if (!quiet)
        {
            Console.Error.WriteLine($"[csharp] ノード {fragment.Nodes.Count} / エッジ {fragment.Edges.Count} → {outPath}（{stopwatch.ElapsedMilliseconds} ms）");
            foreach (var kv in byKind.OrderBy(k => k.Key)) Console.Error.WriteLine($"[csharp]   {kv.Key}: {kv.Value}");
        }
        return 0;
    }

    static void AddNodes(GraphFragment fragment, TypeIndex index, FileResult[] results)
    {
        foreach (var file in results)
        {
            // 候補はあったのに張らなかったバインドは、.cs ノードに残して注釈の入口にする
            if (file.RejectedTypes.Count > 0)
            {
                var names = file.RejectedTypes.Keys.ToList();
                names.Sort(StringComparer.Ordinal);
                var meta = new Dictionary<string, object> { ["rejectedTypes"] = names.Take(12).ToList() };
                if (names.Count > 12) meta["rejectedTypeKinds"] = names.Count;
                fragment.Nodes.Add(new GraphNode
                {
                    Id = NodeId.File(file.RelPath),
                    Kind = "file",
                    Name = Path.GetFileName(file.RelPath),
                    Path = file.RelPath,
                    Metadata = meta,
                });
            }

            foreach (var type in file.Types)
            {
                if (!index.ByQualified.TryGetValue(type.Qualified, out var canonical) || !ReferenceEquals(canonical, type))
                {
                    continue;   // partial の重複宣言は正規ノードに統合済み
                }

                var meta = new Dictionary<string, object>
                {
                    ["csKind"] = type.Kind,
                    ["namespace"] = type.Namespace,
                    ["line"] = type.Line,
                    ["file"] = type.RelPath,
                };
                if (type.Modifiers.Count > 0) meta["modifiers"] = type.Modifiers;
                if (type.BaseRaw.Count > 0) meta["baseTypes"] = type.BaseRaw;
                if (type.OtherFiles.Count > 0) meta["alsoDeclaredIn"] = type.OtherFiles;
                if (type.IsStatic) meta["static"] = true;
                if (type.IsAbstract) meta["abstract"] = true;
                if (type.IsGeneric) meta["generic"] = true;
                meta["memberCount"] = type.MembersByName.Count;

                fragment.Nodes.Add(new GraphNode
                {
                    Id = type.Id,
                    Kind = "type",
                    Name = type.Simple,
                    Parent = type.FileId,
                    Path = type.RelPath,
                    Metadata = meta,
                });
            }

            foreach (var member in file.Members)
            {
                if (!index.ByQualified.TryGetValue(member.Owner.Qualified, out var canonical)) continue;
                if (!canonical.MembersByName.TryGetValue(member.Name, out var canonicalMember) ||
                    !ReferenceEquals(canonicalMember, member))
                {
                    continue;
                }

                var meta = new Dictionary<string, object>
                {
                    ["memberKind"] = member.Kind,
                    ["signature"] = member.Signature,
                    ["line"] = member.Line,
                    ["visibility"] = member.Visibility,
                };
                if (member.ReturnType is not null) meta["returns"] = member.ReturnType;
                if (member.IsStatic) meta["static"] = true;
                if (member.IsAsync) meta["async"] = true;
                if (member.OverloadCount > 1)
                {
                    meta["overloads"] = member.OverloadCount;
                    if (member.ExtraSignatures.Count > 0) meta["otherSignatures"] = member.ExtraSignatures;
                }
                if (member.Unresolved.Count > 0)
                {
                    meta["unresolvedCalls"] = member.Unresolved;
                    if (member.UnresolvedTotal > member.Unresolved.Count) meta["unresolvedTotal"] = member.UnresolvedTotal;
                }

                fragment.Nodes.Add(new GraphNode
                {
                    Id = member.Id,
                    Kind = "member",
                    Name = member.Name,
                    Parent = member.Owner.Id,
                    Path = member.Owner.RelPath,
                    Metadata = meta,
                });
            }
        }
    }

    static List<string> EnumerateFiles(AnalyzerOptions opt)
    {
        var result = new List<string>();
        var stack = new Stack<string>();
        stack.Push(opt.Root);
        while (stack.Count > 0)
        {
            var dir = stack.Pop();
            string[] children;
            try
            {
                children = Directory.GetDirectories(dir);
            }
            catch (Exception)
            {
                continue;
            }
            foreach (var child in children)
            {
                var name = Path.GetFileName(child);
                if (opt.ExcludeDirs.Contains(name)) continue;
                if (name.StartsWith(".") && name != ".") continue;
                stack.Push(child);
            }

            try
            {
                foreach (var file in Directory.GetFiles(dir, "*.cs"))
                {
                    if (file.EndsWith(".xaml.cs", StringComparison.OrdinalIgnoreCase))
                    {
                        continue;   // XAML 生成コードは除外（含まれるとノイズが大きい）
                    }
                    result.Add(file);
                }
            }
            catch (Exception)
            {
                // 読み取り権限のないディレクトリは無視
            }
        }
        result.Sort(StringComparer.Ordinal);
        return result;
    }

    static string ToRelative(string root, string path)
    {
        var rel = Path.GetRelativePath(root, path).Replace('\\', '/');
        return rel.StartsWith("./", StringComparison.Ordinal) ? rel[2..] : rel;
    }
}
