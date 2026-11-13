using System.Text.Json.Serialization;

namespace CsharpDependencyGraph;

/// <summary>
/// 依存グラフの部分断片（fragment）。複数のスキャナ（C#、Terraform、アノテーション）が
/// 同じ ID 規約でノード／エッジを出力し、merge.mjs が 1 つの graph.json に統合する。
/// </summary>
public sealed class GraphFragment
{
    [JsonPropertyName("schemaVersion")] public int SchemaVersion { get; set; } = 1;

    [JsonPropertyName("producer")] public string Producer { get; set; } = "csharp-analyzer";

    [JsonPropertyName("generatedAt")] public string GeneratedAt { get; set; } = "";

    [JsonPropertyName("root")] public string Root { get; set; } = "";

    [JsonPropertyName("nodes")] public List<GraphNode> Nodes { get; set; } = new();

    [JsonPropertyName("edges")] public List<GraphEdge> Edges { get; set; } = new();

    [JsonPropertyName("stats")] public Dictionary<string, int> Stats { get; set; } = new();

    public string ToJson() => System.Text.Json.JsonSerializer.Serialize(this, Json.Options);
}

public sealed class GraphNode
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";

    [JsonPropertyName("kind")] public string Kind { get; set; } = "";

    [JsonPropertyName("name")] public string Name { get; set; } = "";

    [JsonPropertyName("parent")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Parent { get; set; }

    [JsonPropertyName("path")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Path { get; set; }

    [JsonPropertyName("metadata")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public Dictionary<string, object>? Metadata { get; set; }
}

public sealed class GraphEdge
{
    [JsonPropertyName("id")] public string Id { get; set; } = "";

    [JsonPropertyName("source")] public string Source { get; set; } = "";

    [JsonPropertyName("target")] public string Target { get; set; } = "";

    /// <summary>calls / creates / accesses / references / inherits / implements / attribute / project-reference</summary>
    [JsonPropertyName("kind")] public string Kind { get; set; } = "references";

    [JsonPropertyName("detail")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public string? Detail { get; set; }

    /// <summary>static | terraform | annotation | llm</summary>
    [JsonPropertyName("provenance")] public string Provenance { get; set; } = "static";

    [JsonPropertyName("count")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? Count { get; set; }

    [JsonPropertyName("line")]
    [JsonIgnore(Condition = JsonIgnoreCondition.WhenWritingNull)]
    public int? Line { get; set; }

    public static string MakeId(string source, string target, string kind) => $"{kind}:{source}->{target}";
}
