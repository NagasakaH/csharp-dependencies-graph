using Models;

// 型引数の数（アリティ）で候補を絞るとき、`Normalize` が解くのは**最初の name セグメント**である。
// `Outer<int, string>.Inner<Item>` で内側 `Inner<Item>` の 1 引数を外側の候補に適用すると、
// 内側型を持たない別名前空間の `App.Outer<A>`（1 引数）を誤って通してしまう。
// C# コンパイラは `using Models;` 側（2 引数）へ解決するので、そこへ張れていなければ回帰。
namespace Models
{
    public class Item { public int Id { get; set; } }

    public class Outer<A, B>
    {
        public class Inner<C>
        {
            public C this[int i] => default!;
        }
    }
}

namespace App
{
    public class Outer<A> { }

    public class Consumer
    {
        public object Create() => new Outer<int, string>.Inner<Item>();

        public int Read(Outer<int, string>.Inner<Item> p) => p[0].Id;
    }
}
