namespace Fix.Chain.Models;

// 正しい解決先。Consumer 側には `.Id` を持つ別物があるので、型引数を畳むとこちらに届かない
public class RealItem
{
    public string Id => "real";
}

public class Box<T>
{
    public RealItem Make() => new RealItem();
    public RealItem Current => new RealItem();
    public void Go() { }
}
