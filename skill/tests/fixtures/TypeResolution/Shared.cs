namespace Fixtures.TypeResolution.Shared;

/// <summary>型パラメータを 1 つ持つ共有型。`using` と `global using` の両方から届く。</summary>
public class Box<TValue>
{
    public TValue? Value { get; set; }
}
