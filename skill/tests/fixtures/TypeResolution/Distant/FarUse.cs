namespace Fixtures.TypeResolution.Distant;

/// <summary>
/// MSBuild の implicit global using（csproj の `&lt;Using Include&gt;`）でやっと通る参照。
/// cgd は obj/ を読まないため到達性を見込めず、エッジは張らない。
/// </summary>
public class LeaseReader
{
    public Lease<int> Read(int id) => new Lease<int> { Id = id };
}
