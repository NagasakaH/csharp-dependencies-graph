using System.Collections.Generic;

namespace Fix.TupleArg.Models;

public class Item
{
    public int Id => 1;
}

/// <summary>型引数が 1 つの箱。タプルを型引数に受ける側の宣言。</summary>
public class Box<T>
{
    public Item Next => new Item();
    public Item MakeItem() => new Item();
    public Item this[int index] => new Item();
}

/// <summary>型引数が 2 つ。片方がタプルでも個数が 2 に数えるかを見る。</summary>
public class Pair<TKey, TValue>
{
    public Item Key => new Item();
}

public class Provider
{
    public Box<(int, string)> Make() => new Box<(int, string)>();
    public Dictionary<(int, string), Item> Map { get; } = new Dictionary<(int, string), Item>();
    public List<Box<(int, string)>> Batches { get; } = new List<Box<(int, string)>>();
    public Pair<(int, int), string> TwoArgs() => new Pair<(int, int), string>();

    Box<(int, string)> _field = new Box<(int, string)>();

    public int FromField() => _field.MakeItem().Id;
}

public class Consumer
{
    // 型引数がタプルでもプロパティ連鎖が繋がる
    public int ChainProperty(Provider p) => p.Make().Next.Id;

    // 型引数がタプルでも呼び出し連鎖が繋がる
    public int ChainCall(Provider p) => p.Make().MakeItem().Id;

    // indexer の値型（第 2 引数）をタプル付き辞書から取り出す
    public int ThroughDictionary(Provider p) => p.Map[(1, "a")].Id;

    // foreach 要素（List<Box<(int, string)>>）をさらに辿る
    public int ThroughForEach(Provider p)
    {
        var total = 0;
        foreach (var b in p.Batches) total += b.MakeItem().Id;
        return total;
    }

    // var 経由でも同じ型に決まる
    public int ViaVar(Provider p)
    {
        var box = p.Make();
        return box.Next.Id;
    }

    // 型引数が 2 つの宣言にタプルを渡しても個数を誤らない
    public int TwoArgs(Provider p) => p.TwoArgs().Key.Id;
}
