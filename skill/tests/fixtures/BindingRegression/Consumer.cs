using Fix.Regress.Services;

namespace Fix.Regress.Handlers;

// `Fix.Regress.Models` と `Fix.Regress.Core` を using していないファイルからの多段アクセス
public class Worker
{
    public string FromParam(Runner r) => r.Current.Id;

    public string FromLocal()
    {
        var r = new Runner();
        return r.Current.Id;
    }

    public string FromCall(Runner r) => r.Make().Id;

    public void Configure(Feature f) => f.Module.Configure();
}
