using Fixtures.TypeResolution.Shared;

namespace Fixtures.TypeResolution.Explicit;

/// <summary>自分の `using` で届いていて、かつ型引数の数が合うケース。</summary>
public class BoxUser
{
    public Box<int> Make() => new Box<int>();
}
