using System.Collections.Generic;
using Fix.Chain.Models;
using Fix.Chain.Services;
using Fix.Chain.Wrong;

namespace Fix.Chain.App;

// 式の一部は正しい `Models.Box<T>` に繋がり、その先だけ `Wrong` に化ける形を再現する
public class Consumer
{
    public void ForeachImmediate(Provider p)
    {
        foreach (var x in p.All()) x.Go();
    }

    public void ForeachDeferred(Provider p)
    {
        var items = p.All();
        foreach (var x in items) x.Go();
    }

    public void ViaIndexer(Provider p)
    {
        var items = p.All();
        var x = items[0];
        x.Go();
    }

    public string ChainCall(Provider p) => p.All()[0].Make().Id;

    public string ChainProperty(Box<int> box) => box.Current.Id;

    public string VarCallChain(Box<int> box)
    {
        var item = box.Make();
        return item.Id;
    }

    public void ForEachParam(List<Box<int>> boxes)
    {
        foreach (var box in boxes) box.Go();
    }
}
