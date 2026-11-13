namespace CsharpDependencyGraph;

/// <summary>型・メンバーの名前インデックスと、構造的な名前解決。</summary>
public sealed class TypeIndex
{
    readonly int _maxAmbiguous;
    public readonly Dictionary<string, TypeSymbol> ByQualified = new(StringComparer.Ordinal);
    public readonly Dictionary<string, List<TypeSymbol>> BySimple = new(StringComparer.Ordinal);
    public int MergedPartials;

    public TypeIndex(int maxAmbiguous = 2) => _maxAmbiguous = Math.Max(1, maxAmbiguous);

    public void Ingest(FileResult file)
    {
        foreach (var type in file.Types)
        {
            type.DeclaringFile = file;
            if (ByQualified.TryGetValue(type.Qualified, out var canonical))
            {
                if (ReferenceEquals(canonical, type)) continue;
                // partial クラスの別ファイルを正規ノードに束ねる
                canonical.DeclarationCount += type.DeclarationCount;
                if (type.RelPath != canonical.RelPath && !canonical.OtherFiles.Contains(type.RelPath))
                {
                    canonical.OtherFiles.Add(type.RelPath);
                }
                foreach (var kv in type.MembersByName)
                {
                    if (!canonical.MembersByName.ContainsKey(kv.Key)) canonical.MembersByName[kv.Key] = kv.Value;
                }
                MergedPartials++;
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

    /// <summary>宣言中に現れた型名テキストを、インデックス中の型に解決する。</summary>
    public IReadOnlyList<TypeSymbol> Resolve(string raw, string ns, FileResult? file)
    {
        var name = TypeText.Normalize(raw);
        if (name.Length == 0 || name[0] == '<') return EmptyTypes;

        if (file is not null && file.Aliases.TryGetValue(name, out var aliased))
        {
            name = TypeText.Normalize(aliased);
            if (name.Length == 0) return EmptyTypes;
        }

        if (ByQualified.TryGetValue(name, out var exact)) return new[] { exact };
        if (name.Contains('.') && ByQualified.TryGetValue(name.Replace('.', '/'), out var flatNested))
        {
            return new[] { flatNested };
        }
        if (ns.Length > 0 && ByQualified.TryGetValue(ns + "." + name, out var inNamespace)) return new[] { inNamespace };
        if (ns.Length > 0 && name.Contains('.') &&
            ByQualified.TryGetValue(ns + "." + name.Replace('.', '/'), out var nestedInNamespace))
        {
            return new[] { nestedInNamespace };
        }

        if (file is not null)
        {
            foreach (var usingNs in file.Usings)
            {
                if (ByQualified.TryGetValue(usingNs + "." + name, out var byUsing)) return new[] { byUsing };
                if (name.Contains('.') && ByQualified.TryGetValue(usingNs + "." + name.Replace('.', '/'), out var byUsingNested))
                {
                    return new[] { byUsingNested };
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
                        if (ByQualified.TryGetValue(candidate.Qualified + "/" + rest, out var inner))
                        {
                            return new[] { inner };
                        }
                    }
                }
            }
        }

        if (BySimple.TryGetValue(name, out var candidates))
        {
            if (candidates.Count == 1) return new[] { candidates[0] };

            var scored = new List<(int Score, TypeSymbol Type)>(candidates.Count);
            foreach (var candidate in candidates)
            {
                var score = 0;
                if (candidate.Namespace.Length > 0)
                {
                    if (string.Equals(candidate.Namespace, ns, StringComparison.Ordinal)) score += 6;
                    else if (ns.StartsWith(candidate.Namespace + ".", StringComparison.Ordinal)) score += 3;
                }
                if (file is not null)
                {
                    foreach (var usingNs in file.Usings)
                    {
                        if (string.Equals(usingNs, candidate.Namespace, StringComparison.Ordinal)) { score += 5; break; }
                    }
                    foreach (var usingNs in file.Usings)
                    {
                        if (candidate.Namespace.StartsWith(usingNs + ".", StringComparison.Ordinal)) { score += 1; break; }
                    }
                }
                scored.Add((score, candidate));
            }

            scored.Sort((a, b) => b.Score.CompareTo(a.Score));
            if (scored.Count == 1 || scored[0].Score > scored[1].Score) return new[] { scored[0].Type };
            if (scored[0].Score == 0) return EmptyTypes;         // 判別できない曖昧さは張らない

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
