namespace CsharpDependencyGraph;

public sealed class FileResult
{
    public string RelPath = "";
    public List<string> Usings = new();
    /// <summary>`global using X;` で宣言された名前空間（同じプロジェクト配下の全ファイルに見える）。</summary>
    public List<string> GlobalUsings = new();
    public Dictionary<string, string> Aliases = new();
    public List<TypeSymbol> Types = new();
    public List<MemberSymbol> Members = new();
    public Dictionary<string, int> UnresolvedTypes = new(StringComparer.Ordinal);
    /// <summary>候補は見つかったが到達性や型引数の数が合わず張らなかった型名（注釈の候補として残す）。</summary>
    public Dictionary<string, int> RejectedTypes = new(StringComparer.Ordinal);
    public bool ParseFailed;
}

public sealed class TypeSymbol
{
    public string Qualified = "";     // NS.Outer/Inner
    public string Simple = "";
    public string Kind = "class";     // class|interface|struct|record|enum|delegate
    public string Namespace = "";
    public string RelPath = "";
    public int Line;
    public bool IsStatic;
    public bool IsAbstract;
    public bool IsSealed;
    public bool IsGeneric;
    /// <summary>宣言中の型パラメータの数（`Dictionary<TKey, TValue>` なら 2）。使用側の型引数の数と突き合わせて誤バインドを止める。</summary>
    public int Arity;
    /// <summary>このノード ID に畳まれた型パラメータ数の一覧。`Activity` と `Activity<T>` は同じ ID を共有する。</summary>
    public List<int> Arities = new(1);
    /// <summary>使用側に書かれた型引数の数を受けつけるか。</summary>
    public bool MatchesArity(int usageArity) => Arities.Count == 0 || Arities.Contains(usageArity);
    public int DeclarationCount;
    public List<string> BaseRaw = new();
    public List<string> Modifiers = new();
    public List<string> OtherFiles = new();
    public FileResult DeclaringFile = null!;
    public readonly Dictionary<string, MemberSymbol> MembersByName = new(StringComparer.Ordinal);

    public string Id => NodeId.Type(Qualified);
    public string FileId => NodeId.File(RelPath);
}

public sealed class MemberSymbol
{
    public TypeSymbol Owner = null!;
    public string Name = "";          // ".ctor" も含む
    public string Kind = "method";    // method|constructor|property|field|event|enum-member|operator|indexer
    public string Signature = "";
    public string? ReturnType;
    public int Line;
    public bool IsStatic;
    public bool IsAsync;
    public string Visibility = "public";
    public int OverloadCount;
    public List<string> ExtraSignatures = new();
    public List<string> Unresolved = new();
    public int UnresolvedTotal;
    public string Id => NodeId.Member(Owner.Qualified, Name);
}

public sealed class AnalyzerOptions
{
    public string Root = "";
    public HashSet<string> ExcludeDirs = new(StringComparer.OrdinalIgnoreCase)
    {
        "bin", "obj", ".git", ".vs", ".vscode", ".idea", "node_modules",
        "TestResults", "artifacts", "packages", ".nuget", "coverage", "wwwroot",
    };
    public bool DeclarationTypeRefs = true;
    public bool AccessEdges = true;
    public int MaxAmbiguous = 2;
    public int MaxUnresolvedPerMember = 8;
    public int MaxFiles = 0;
}

public static class Json
{
    public static readonly System.Text.Json.JsonSerializerOptions Options = new()
    {
        DefaultIgnoreCondition = System.Text.Json.Serialization.JsonIgnoreCondition.WhenWritingNull,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        WriteIndented = false,
    };
}

/// <summary>ノード ID 規約（scan.mjs / analyzer / merge.mjs で共通）。</summary>
public static class NodeId
{
    public static string Folder(string relDir) => relDir.Length == 0 ? "folder:." : "folder:" + relDir;

    public static string File(string relPath) => "file:" + relPath;

    public static string Project(string relPath) => "project:" + relPath;

    public static string Type(string qualified) => "type:" + qualified;

    public static string Member(string qualifiedType, string memberName) =>
        "member:" + qualifiedType + "." + memberName;
}
