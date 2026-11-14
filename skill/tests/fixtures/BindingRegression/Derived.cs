namespace Fix.Regress.Core.Activities;

// 内側の名前空間からは `using` 無しで outer の型が見える。型引数付きの基底型を結べるか
public sealed class Dispatch : Activity<object> { }

public sealed class If : Activity<bool> { }
