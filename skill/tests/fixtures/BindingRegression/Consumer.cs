using Fix.Regress.Boxes;
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

    // 戻り値型を `var` で一度受けると、型表記は Consumer.cs に書かれない。
    // 宣言元（Services.cs）の using を運んでいないとここで解決が切れる
    public string VarFromCall(Runner r)
    {
        var item = r.Make();
        return item.Id;
    }

    public string VarFromProperty(Runner r)
    {
        var item = r.Current;
        return item.Id;
    }

    public int VarInForEach(Runner r)
    {
        var total = 0;
        foreach (var item in r.All()) total += item.Id.Length;
        return total;
    }

    public string VarFromIndexer(Runner r)
    {
        var items = r.All();
        var first = items[0];
        return first.Id;
    }

    // 同じ名前空間に型パラメータ数の違う `Box` があっても、`Box<int>` は Boxes のほうへ進む
    public void Go(Box b) => b.Identity();

    public int ArityFromParam(Box<int> box)
    {
        box.Go();
        return box.Value;
    }
}

// 型パラメータを持たない同名型（`Box<int>` の解決で飛ばすべき候補）
public class Box
{
    public string Id => "x";

    public void Identity() { }
}
