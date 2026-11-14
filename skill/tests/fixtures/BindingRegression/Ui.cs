using System.Collections.Generic;

namespace Fix.Regress.Ui;

// 同名の非ジェネリック型が同じ名前空間にあれば、型引数を書いた利用は BCL 側。
// 確定解決の経路（名前空間修飾なしの単純名）でも型引数の数を必ず見る
public class Dictionary { }

public class PanelHost
{
    public object Make() => new Dictionary<string, int>();
}
