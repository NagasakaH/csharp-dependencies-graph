using System.Text;

namespace CsharpDependencyGraph;

/// <summary>型名テキストの正規化ユーティリティ（構文解決用）。</summary>
public static class TypeText
{

    /// <summary>`List&lt;Foo&gt;?[]` → `List` のような正規化。</summary>
    public static string Normalize(string raw)
    {
        if (string.IsNullOrWhiteSpace(raw)) return "";
        var s = StripComments(raw).Trim();
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

    /// <summary>型表記の文字列からコメントを除く。`ToString()` はノードの**内側**のコメントを残すため、
    /// `Pair&lt;int /* index [start */, string&gt;` のような書き方は構文上の括弧でない `[` を含んだ文字列になる。
    /// 括弧の深さを数える処理はこれを先に除かないと、型引数の数を誤って数える
    /// （誤って多く数えると正常な連鎖を黙って消す）。</summary>
    public static string StripComments(string? raw)
    {
        if (string.IsNullOrEmpty(raw)) return "";
        var s = raw!;
        if (s.IndexOf('/') < 0) return s;
        var sb = new StringBuilder(s.Length);
        var line = -1;
        for (var i = 0; i < s.Length; i++)
        {
            var c = s[i];
            if (line >= 0)
            {
                if (c == '\n') { line = -1; sb.Append(' '); }
                continue;
            }
            if (c == '/' && i + 1 < s.Length && s[i + 1] == '/') { line = i; i++; continue; }
            if (c == '/' && i + 1 < s.Length && s[i + 1] == '*')
            {
                var end = s.IndexOf("*/", i + 2, StringComparison.Ordinal);
                if (end < 0) break;
                sb.Append(' ');
                i = end + 1;
                continue;
            }
            sb.Append(c);
        }
        return sb.ToString();
    }

    /// <summary>型引数が付いている name セグメントへ切る。`Outer&lt;Wrong&gt;.Items&lt;Correct&gt;` の型引数は
    /// 左の `Outer` ではなく**右の `Items`** に付いている（外側のものを返すと、その先で別物の型へ張る）。
    /// `System.Collections.Generic.List&lt;int&gt;` のように閉じた `&gt;` が無いときの `.` では切らない。</summary>
    public static string GenericCarrier(string? raw)
    {
        var s = StripComments(raw);
        if (s.IndexOf('<') < 0) return s;
        var cut = -1;
        var depth = 0;
        var closed = false;
        for (var i = 0; i < s.Length; i++)
        {
            var c = s[i];
            if (c == '<') { depth++; closed = false; }
            else if (c == '>') { depth--; if (depth == 0) closed = true; }
            else if (c == '.' && depth == 0 && closed) { cut = i; closed = false; }
        }
        return cut < 0 ? s : s[(cut + 1)..];
    }

    /// <summary>`Task&lt;Foo&gt;` → `Foo`、`ValueTask&lt;Foo&gt;` → `Foo`。それ以外はそのまま。</summary>
    public static string UnwrapTask(string? raw)
    {
        if (string.IsNullOrEmpty(raw)) return "";
        var s = StripComments(raw).Trim();
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
    /// 後ろに別のジェネリックが続いても最後の `&gt;` を拾わない）。
    /// 型引数が付いている name セグメントは <see cref="GenericCarrier"/> で選んでから割る。</summary>
    public static List<string> GenericArgs(string? raw)
    {
        var result = new List<string>();
        if (string.IsNullOrEmpty(raw)) return result;
        var s = GenericCarrier(raw);
        if (s.IndexOf('<') < 0) return result;
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
