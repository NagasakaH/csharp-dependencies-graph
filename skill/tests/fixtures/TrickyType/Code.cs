using System.Collections.Generic;

namespace Fix.TrickyType;

// 型引数の数を数えるとき、コメントの中の括弧は構文上の括弧ではない。
// `Outer<Wrong>.Items<Correct>` の型引数は左の `Outer` ではなく右の `Items` に付いている。
// 取り違えると `Wrong.Id` へ断定したエッジを張るので、`Wrong` を置いて検出できるようにする。
public class Wrong { public int Id { get; set; } }

public class Correct { public int Id { get; set; } }

public class Item { public int Id { get; set; } }

public class Outer<T>
{
    public class Items<U>
    {
        public U this[int index] => default!;
    }
}

public class Pair<A, B>
{
    public Item Next { get; set; } = new();
}

public class Consumer
{
    // ネストしたジェネリック型の indexer を辿る
    public int NestedIndexer(Outer<Wrong>.Items<Correct> p) => p[0].Id;

    public int NestedField()
    {
        Outer<Wrong>.Items<Correct> items = null!;
        return items[0].Id;
    }

    // コメントの中の `[` で型引数の数を誤らない
    public int BlockComment(Pair<int /* index [start */, string> p) => p.Next.Id;

    public int DictComment(Dictionary<int /* index [start */, Item> p) => p[0].Id;

    // 型表記の途中に行コメントが入っても同じ
    public int LineComment(Pair<int // [start
        , string> p) => p.Next.Id;
}
