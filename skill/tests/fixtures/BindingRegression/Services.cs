using System.Collections.Generic;
using Fix.Regress.Core;
using Fix.Regress.Models;

namespace Fix.Regress.Services;

// 戻り値型 `Item` / `IModule` はここ（Services.cs）の using で見えている。
// 使う側がこれらの名前空間を import する必要は C# にはない
public class Runner
{
    public Item Current { get; } = new Item();

    public Item Make() => new Item();

    public List<Item> All() => new List<Item>();
}

public class Feature
{
    public IModule Module { get; } = null!;
}
