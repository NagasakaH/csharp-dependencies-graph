namespace Fix.Chain.Wrong;

// 畳んだ名前 `Box` / 宣言元を無視した `Item` が化ける側（第 11 ラウンドの再現そのまま）
public class WrongItem
{
    public string Id => "wrong";
}

public class Box
{
    public WrongItem Make() => new WrongItem();
    public WrongItem Current => new WrongItem();
    public void Go() { }
}
