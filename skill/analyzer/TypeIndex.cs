namespace CsharpDependencyGraph;

/// <summary>型・メンバーの名前インデックスと、構造的な名前解決。</summary>
public sealed class TypeIndex
{
    readonly int _maxAmbiguous;
    public readonly Dictionary<string, TypeSymbol> ByQualified = new(StringComparer.Ordinal);
    public readonly Dictionary<string, List<TypeSymbol>> BySimple = new(StringComparer.Ordinal);
    public int MergedPartials;
    /// <summary>`Activity` と `Activity<T>` のように、型パラメータ数が違い同じ ID に畳まれた件数。</summary>
    public int ArityMerges;
    /// <summary>`global using` した名前空間を、宣言したディレクトリの子孫から見える形にしたもの。</summary>
    readonly Dictionary<string, List<string>> _globalUsings = new(StringComparer.Ordinal);

    /// <summary>候補があったのにエッジを張らなかった理由。</summary>
    public enum RejectReason { None, ArityMismatch, Unreachable }

    public TypeIndex(int maxAmbiguous = 2) => _maxAmbiguous = Math.Max(1, maxAmbiguous);

    /// <summary>ファイルから見える `using` の集合。`global using` は親ディレクトリ由来でも見える。</summary>
    IEnumerable<string> VisibleUsings(FileResult? file)
    {
        if (file is null) yield break;
        foreach (var u in file.Usings) yield return u;
        if (_globalUsings.Count == 0) yield break;
        var dir = DirOf(file.RelPath);
        while (true)
        {
            if (_globalUsings.TryGetValue(dir, out var list))
            {
                foreach (var u in list) yield return u;
            }
            if (dir.Length == 0) yield break;
            var cut = dir.LastIndexOf('/');
            dir = cut < 0 ? "" : dir[..cut];
        }
    }

    static string DirOf(string relPath)
    {
        var cut = relPath.LastIndexOf('/');
        return cut < 0 ? "" : relPath[..cut];
    }

    public void Ingest(FileResult file)
    {
        foreach (var globalUsing in file.GlobalUsings)
        {
            var dir = DirOf(file.RelPath);
            if (!_globalUsings.TryGetValue(dir, out var list))
            {
                list = new List<string>(4);
                _globalUsings[dir] = list;
            }
            if (!list.Contains(globalUsing)) list.Add(globalUsing);
        }
        foreach (var type in file.Types)
        {
            type.DeclaringFile = file;
            if (type.Arities.Count == 0) type.Arities.Add(type.Arity);
            if (ByQualified.TryGetValue(type.Qualified, out var canonical))
            {
                if (ReferenceEquals(canonical, type)) continue;
                // partial クラスの別ファイルを正規ノードに束ねる
                canonical.DeclarationCount += type.DeclarationCount;
                if (!canonical.Arities.Contains(type.Arity))
                {
                    // 同一名前空間の `Activity` と `Activity<T>` は別宣言でも同じノード ID を使う。
                    // 片方に寄せるのではなく両方の型パラメータ数を覚えて、型引数のゲートで受けつける
                    canonical.Arities.Add(type.Arity);
                    ArityMerges++;
                }
                else
                {
                    MergedPartials++;
                }
                if (type.RelPath != canonical.RelPath && !canonical.OtherFiles.Contains(type.RelPath))
                {
                    canonical.OtherFiles.Add(type.RelPath);
                }
                foreach (var kv in type.MembersByName)
                {
                    if (!canonical.MembersByName.ContainsKey(kv.Key)) canonical.MembersByName[kv.Key] = kv.Value;
                }
                continue;
            }
            ByQualified[type.Qualified] = type;
            if (!BySimple.TryGetValue(type.Simple, out var list))
            {
                list = new List<TypeSymbol>(2);
                BySimple[type.Simple] = list;
            }
            list.Add(type);
        }
    }

    static readonly TypeSymbol[] EmptyTypes = Array.Empty<TypeSymbol>();

    /// <summary>候補の名前空間が使用側から届いているかの変換（点けられないなら 0）。</summary>
    int ScoreReach(TypeSymbol candidate, string ns, FileResult? file)
    {
        var score = 0;
        // 宣言と同じファイルから使う型が最も強い手掛かり。
        // グローバル名前空間の型（`Program` とそのネスト型）は名前空間が空なので、これがないと届かない
        if (file is not null && ReferenceEquals(candidate.DeclaringFile, file)) score += 6;
        if (candidate.Namespace.Length == 0)
        {
            if (ns.Length == 0) score += 6;
        }
        else if (string.Equals(candidate.Namespace, ns, StringComparison.Ordinal)) score += 6;
        else if (ns.StartsWith(candidate.Namespace + ".", StringComparison.Ordinal)) score += 3;
        if (file is not null)
        {
            var exact = false;
            var ancestor = false;
            foreach (var usingNs in VisibleUsings(file))
            {
                if (!exact && string.Equals(usingNs, candidate.Namespace, StringComparison.Ordinal)) exact = true;
                if (!ancestor && candidate.Namespace.StartsWith(usingNs + ".", StringComparison.Ordinal)) ancestor = true;
            }
            if (exact) score += 5;
            else if (ancestor) score += 1;
        }
        return score;
    }

    /// <summary>使用側に書かれた型引数の数。閉じないなど判定不能なら 0（ゲートは発動しない）。
    /// タプル型引数 `Box&lt;(int, string)&gt;` のカンマは型引数の区切りではないので、
    /// 丸括弧と角括弧の内側では数えない（数えると 1 引数の `Box&lt;T&gt;` を 2 引数として
    /// 拒否し、その先へ張るべき連鎖ごと消える）。</summary>
    static int UsageArity(string raw)
    {
        var lt = raw.IndexOf('<');
        if (lt <= 0) return 0;
        var depth = 0;
        var nest = 0;
        var commas = 0;
        for (var i = lt; i < raw.Length; i++)
        {
            var c = raw[i];
            if (c == '<') depth++;
            else if (c == '>')
            {
                depth--;
                if (depth == 0) return commas + 1;
            }
            else if (c == '(' || c == '[') nest++;
            else if (c == ')' || c == ']') nest--;
            else if (c == ',' && depth == 1 && nest == 0) commas++;
        }
        return 0;
    }

    /// <summary>宣言中に現れた型名テキストを、インデックス中の型に解決する。</summary>
    public IReadOnlyList<TypeSymbol> Resolve(string raw, string ns, FileResult? file)
        => Resolve(raw, ns, file, out _);

    /// <summary>解決しなかったとき `reject` に断った理由が入る（候補すらない場合は None）。
    /// 理由は呼び出し単位のローカルで受け取る（解析はファイルを並列に回すので、共有フィールドに書くと競合する）。</summary>
    public IReadOnlyList<TypeSymbol> Resolve(string raw, string ns, FileResult? file, out RejectReason reject)
    {
        var box = new RejectBox();
        var result = ResolveCore(raw, ns, file, box, UsageArity(raw));
        reject = box.Reason;
        return result;
    }

    sealed class RejectBox
    {
        public RejectReason Reason;
    }

    IReadOnlyList<TypeSymbol> ResolveCore(string raw, string ns, FileResult? file, RejectBox box, int usageArity)
    {
        // ゲート 1: 使用側が型引数を書いているなら、宣言の型パラメータ数が違う候補には張らない
        //   （`Dictionary<string, object>` を Blazor の非ジェネリック `Dictionary` に化かさない）。
        //   名前解決の形を絞らず、確定解決の経路でも必ず通す。
        //   ただし C# は不一致の候補を**飛ばして次を探索する**ので、ここで引き返さない。
        var sawArityMismatch = false;
        TypeSymbol? hit = null;
        bool Take(TypeSymbol candidate)
        {
            if (usageArity > 0 && !candidate.MatchesArity(usageArity))
            {
                sawArityMismatch = true;
                return false;
            }
            hit = candidate;
            return true;
        }

        var name = TypeText.Normalize(raw);
        if (name.Length == 0 || name[0] == '<') return EmptyTypes;

        if (file is not null && file.Aliases.TryGetValue(name, out var aliased))
        {
            name = TypeText.Normalize(aliased);
            if (name.Length == 0) return EmptyTypes;
        }

        if (ByQualified.TryGetValue(name, out var exact) && Take(exact)) return new[] { hit! };
        if (name.Contains('.') && ByQualified.TryGetValue(name.Replace('.', '/'), out var flatNested) &&
            Take(flatNested))
        {
            return new[] { hit! };
        }
        if (ns.Length > 0 && ByQualified.TryGetValue(ns + "." + name, out var inNamespace) && Take(inNamespace))
        {
            return new[] { hit! };
        }
        if (ns.Length > 0 && name.Contains('.') &&
            ByQualified.TryGetValue(ns + "." + name.Replace('.', '/'), out var nestedInNamespace) &&
            Take(nestedInNamespace))
        {
            return new[] { hit! };
        }

        if (file is not null)
        {
            foreach (var usingNs in VisibleUsings(file))
            {
                if (ByQualified.TryGetValue(usingNs + "." + name, out var byUsing) && Take(byUsing))
                    return new[] { hit! };
                if (name.Contains('.') &&
                    ByQualified.TryGetValue(usingNs + "." + name.Replace('.', '/'), out var byUsingNested) &&
                    Take(byUsingNested))
                {
                    return new[] { hit! };
                }
            }

            var dot = name.IndexOf('.');
            if (dot > 0)
            {
                // `Outer.Inner` の Outer が既知のネスト型親かもしれない
                var outer = name[..dot];
                var rest = name[(dot + 1)..].Replace('.', '/');
                if (BySimple.TryGetValue(outer, out var outers))
                {
                    foreach (var candidate in outers)
                    {
                        if (ByQualified.TryGetValue(candidate.Qualified + "/" + rest, out var inner) && Take(inner))
                        {
                            return new[] { hit! };
                        }
                    }
                }
            }
        }

        if (BySimple.TryGetValue(name, out var bySimple))
        {
            var candidates = bySimple;
            if (usageArity > 0)
            {
                var typed = new List<TypeSymbol>(bySimple.Count);
                foreach (var candidate in bySimple)
                {
                    if (candidate.MatchesArity(usageArity)) typed.Add(candidate);
                }
                if (typed.Count == 0)
                {
                    box.Reason = RejectReason.ArityMismatch;
                    return EmptyTypes;
                }
                candidates = typed;
            }

            var scored = new List<(int Score, TypeSymbol Type)>(candidates.Count);
            foreach (var candidate in candidates)
            {
                var score = ScoreReach(candidate, ns, file);
                scored.Add((score, candidate));
            }

            scored.Sort((a, b) => b.Score.CompareTo(a.Score));
            // ゲート 2: 候補が 1 件でも、名前空間・内側・`using`（global 含む）のいずれでも
            //   届かないなら張らない。BCL 型は索引に無いので「解 1 件」は到達性の証拠にならない。
            if (scored[0].Score == 0)
            {
                box.Reason = RejectReason.Unreachable;
                return EmptyTypes;                              // 届かない／判別できない曖昧さは張らない
            }
            if (scored.Count == 1 || scored[0].Score > scored[1].Score) return new[] { scored[0].Type };

            var top = scored[0].Score;
            var picked = new List<TypeSymbol>();
            foreach (var entry in scored)
            {
                if (entry.Score != top) break;
                picked.Add(entry.Type);
                if (picked.Count >= _maxAmbiguous) break;
            }
            return picked;
        }

        // 型引数の数で弾いただけで何も決まらなかった、という理由を残す
        if (sawArityMismatch) box.Reason = RejectReason.ArityMismatch;
        return EmptyTypes;
    }

    /// <summary>基底クラスとインターフェースを辿ってメンバーを探す。</summary>
    public MemberSymbol? FindMember(TypeSymbol start, string name, int maxDepth = 4)
    {
        if (start.MembersByName.TryGetValue(name, out var own)) return own;

        var visited = new HashSet<TypeSymbol>(ReferenceEqualityComparer.Instance) { start };
        var queue = new Queue<(TypeSymbol Type, int Depth)>();
        queue.Enqueue((start, 0));

        while (queue.Count > 0)
        {
            var (current, depth) = queue.Dequeue();
            if (depth >= maxDepth) continue;
            foreach (var baseRaw in current.BaseRaw)
            {
                foreach (var baseType in Resolve(baseRaw, current.Namespace, current.DeclaringFile))
                {
                    if (!visited.Add(baseType)) continue;
                    if (baseType.MembersByName.TryGetValue(name, out var inherited))
                    {
                        return inherited;
                    }
                    queue.Enqueue((baseType, depth + 1));
                }
            }
        }
        return null;
    }

    public bool TryGetNested(TypeSymbol parent, string simpleName, out TypeSymbol nested)
    {
        if (ByQualified.TryGetValue(parent.Qualified + "/" + simpleName, out nested!)) return true;
        nested = null!;
        return false;
    }
}
