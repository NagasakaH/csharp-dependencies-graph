using System.Collections.Generic;

namespace Fixtures.TypeResolution.Core;

/// <summary>別名前空間に非ジェネリックの同名クラスがある中の、BCL 側の実利用。</summary>
public class Registry
{
    public Dictionary<string, int> Counts { get; } = new Dictionary<string, int>();

    public int Total()
    {
        var scratch = new Dictionary<string, int>();
        scratch["a"] = 1;
        return scratch.Count;
    }
}

/// <summary>`global using` だけで Shared が見えているケース。</summary>
public class GlobalBoxUser
{
    public Box<string> Make() => new Box<string>();
}
