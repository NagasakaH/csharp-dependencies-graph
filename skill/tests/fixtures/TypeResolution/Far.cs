namespace Fixtures.TypeResolution.Far;

/// <summary>型引数の数は合うが、cgd から見て到達できない名前空間に置く型。</summary>
public class Lease<TId>
{
    public TId Id { get; set; } = default!;
}
