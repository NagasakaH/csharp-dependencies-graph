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

public class Widget { public void Handle() { } public int Size; }
public class Gadget { public void Handle() { } public int Size; }

public class Maker
{
    public static Widget Make() => new();

    /// <summary>静的解析では型が決まらない経路（dynamic）で、有効な C# のまま未解決を再現する。</summary>
    public static dynamic Unknown() => new object();
}

/// <summary>
/// `var` の型を 2 ラウンド目で推論するとき、その結果が後続ブロックの宣言を潰さないこと。
/// 推論結果を列の末尾に足すと「直前に見えた宣言」の順序が崩れて後勝ちになる（レビュー指摘）。
/// </summary>
public class DeferredShadowing
{
    public void Run()
    {
        { var x = Maker.Make(); x.Handle(); _ = x.Size; }
        { var x = new Gadget(); x.Handle(); _ = x.Size; }
    }
}

/// <summary>型が決まらない `var` を、先頭ブロックの型で断定しないこと（偽陽性の回帰）。</summary>
public class UnknownShadowing
{
    public void Run()
    {
        { var x = Maker.Make(); _ = x.Size; }
        { var x = Maker.Unknown(); x.Handle(); }
    }

    public void Guard()
    {
        var y = Maker.Make();
        y.Handle();
    }
}

/// <summary>C# のローカル関数は宣言より前でも呼べる。宣言位置より前で型メンバに化けないこと。</summary>
public class EarlyLocalFunction
{
    public void Handle() { }

    public void Run()
    {
        Handle();
        void Handle() { }
    }
}

/// <summary>遅延推論したローカルや `await` / `new` を foreach したときの要素型。</summary>
public class ForeachDeferred
{
    private readonly System.Collections.Generic.List<Item> _direct = new();
    public System.Collections.Generic.List<Item> Items => _direct;

    public void ViaAlias()
    {
        var items = Items;
        foreach (var x in items) x.Handle();
    }

    public void ViaNew()
    {
        foreach (var x in new System.Collections.Generic.List<Item>()) x.Handle();
    }

    public async System.Threading.Tasks.Task ViaAwait()
    {
        foreach (var x in await LoadAsync()) x.Handle();
    }

    private static System.Threading.Tasks.Task<System.Collections.Generic.List<Item>> LoadAsync()
        => System.Threading.Tasks.Task.FromResult(new System.Collections.Generic.List<Item>());
}

/// <summary>
/// 内側ブロックの宣言が、外側の後続コードまで同名の型メンバを隠さないこと。
/// 位置だけで見た場合、この `widget` は後続でも見えてしまいフィールドを誤って隠す。
/// </summary>
public class BlockScopeLeak
{
    private readonly Widget widget = new();

    public void Run()
    {
        { var widget = new Gadget(); widget.Handle(); }
        widget.Handle();
    }
}
