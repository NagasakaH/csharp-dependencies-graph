namespace CsharpDependencyGraph;

/// <summary>型名テキストの正規化ユーティリティ（構文解決用）。</summary>
public static class TypeText
{
    /// <summary>`List&lt;Foo&gt;?[]` → `List` のような正規化。</summary>
    public static string Normalize(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return "";
        var s = raw.Trim();
        if (s.StartsWith("global::", StringComparison.Ordinal)) s = s[8..];
        while (true)
        {
            if (s.EndsWith("[]", StringComparison.Ordinal)) { s = s[..^2]; continue; }
            if (s.EndsWith("?", StringComparison.Ordinal)) { s = s[..^1]; continue; }
            if (s.EndsWith("*", StringComparison.Ordinal)) { s = s[..^1]; continue; }
            break;
        }
        if (s.StartsWith("ref ", StringComparison.Ordinal)) s = s[4..];
        if (s.StartsWith("out ", StringComparison.Ordinal)) s = s[4..];
        if (s.StartsWith("in ", StringComparison.Ordinal)) s = s[3..];
        var lt = s.IndexOf('<');
        if (lt > 0) s = s[..lt];
        return s.Trim();
    }

    /// <summary>`Task&lt;Foo&gt;` → `Foo`、`ValueTask&lt;Foo&gt;` → `Foo`。それ以外はそのまま。</summary>
    public static string UnwrapTask(string? raw)
    {
        if (string.IsNullOrEmpty(raw)) return "";
        var s = raw!.Trim();
        foreach (var prefix in new[] { "ValueTask<", "Task<", "System.Threading.Tasks.ValueTask<", "System.Threading.Tasks.Task<" })
        {
            if (s.StartsWith(prefix, StringComparison.Ordinal))
            {
                var inner = s[prefix.Length..];
                var depth = 1;
                for (var i = 0; i < inner.Length; i++)
                {
                    if (inner[i] == '<') depth++;
                    else if (inner[i] == '>')
                    {
                        depth--;
                        if (depth == 0) return inner[..i].Trim();
                    }
                }
            }
        }
        return s;
    }

    /// <summary>ジェネリック引数を列挙（`Dictionary&lt;string, Foo&gt;` → ["string","Foo"]）。
    /// タプル型引数 `Box&lt;(int, string)&gt;` のカンマは区切りとして割らない。
    /// 対応する `&gt;` は最初の `&lt;` に対して深さで探す（`Box&lt;…&gt;.Inner&lt;…&gt;` のように
    /// 後ろに別のジェネリックが続いても最后一个の `&gt;` を拾わない）。</summary>
    public static List<string> GenericArgs(string? raw)
    {
        var result = new List<string>();
        if (string.IsNullOrEmpty(raw)) return result;
        var s = raw!;
        var lt = s.IndexOf('<');
        if (lt < 0) return result;
        var gt = -1;
        var angle = 0;
        for (var i = lt; i < s.Length; i++)
        {
            if (s[i] == '<') angle++;
            else if (s[i] == '>')
            {
                angle--;
                if (angle == 0) { gt = i; break; }
            }
        }
        if (gt <= lt) return result;
        var inner = s[(lt + 1)..gt];
        var depth2 = 0;
        var nest = 0;
        var start = 0;
        for (var i = 0; i <= inner.Length; i++)
        {
            if (i == inner.Length || (depth2 == 0 && nest == 0 && inner[i] == ','))
            {
                var part = inner[start..i].Trim();
                if (part.Length > 0) result.Add(part);
                start = i + 1;
            }
            else if (inner[i] == '<') depth2++;
            else if (inner[i] == '>') depth2--;
            else if (inner[i] == '(' || inner[i] == '[') nest++;
            else if (inner[i] == ')' || inner[i] == ']') nest--;
        }
        return result;
    }
}
