namespace Fixtures.ScopeAccuracy;

public class A { public void Go() { } public int Value; }
public class B { public void Go() { } public int Value; }
public class Worker { public void Go() { } }

/// <summary>
/// 兄弟ブロックに同じ名前の var があるケース。メソッド全体で 1 つの辞書に畳むと
/// 後勝ちになって A 側のエッジが消える（レビュー指摘）。
/// </summary>
public class SiblingBlocks
{
    public void Run()
    {
        { var x = new A(); x.Go(); _ = x.Value; }
        { var x = new B(); x.Go(); _ = x.Value; }
    }
}

/// <summary>
/// `foreach (var x in …)` の要素型推論。ジェネリックを畳んだ後の型から要素型を取ろうとすると
/// 全滅する（レビュー指摘）。フィールド / 引数 / プロパティ由来の 3 経路を見る。
/// </summary>
public class ForeachElements
{
    private readonly System.Collections.Generic.List<Item> _items = new();
    public System.Collections.Generic.List<Item> Items => _items;

    public void FromField() { foreach (var a in _items) a.Handle(); }
    public void FromParameter(System.Collections.Generic.List<Item> given) { foreach (var b in given) b.Handle(); }
    public void FromProperty() { foreach (var c in Items) c.Handle(); }
}

public class Item { public void Handle() { } }

/// <summary>名前で型メンバを隠す構文の集まり。</summary>
public class Shadowing
{
    public void Go() { }

    // 型を省略したラムダ引数。BuildScope が型なしで登録しないと this.Go に化ける
    public void LambdaParameter()
    {
        System.Action<System.Action> invoke = Go => Go();
        invoke(() => { });
    }

    // ローカル関数。同名の型メンバに張り替えてはいけない
    public void LocalFunction()
    {
        void Go() { }
        Go();
    }

    // 前の兄弟ブロックでは this.Go が正しい。位置対応を緩めすぎるとこれも消える
    public void SiblingThenCall()
    {
        { Go(); }
        { System.Action Go = () => { }; Go(); }
    }

    // var 推論はこのスコープ実装でも壊れてはいけない
    public void InferredVar()
    {
        var w = new Worker();
        w.Go();
    }
}
