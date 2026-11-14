namespace Fixtures.TypeResolution.Ui;

/// <summary>
/// 非ジェネリックの同名クラス。実測で `System.Collections.Generic.Dictionary&lt;TKey, TValue&gt;` が
/// この型に誤バインドした（elsa-core の Blazor コンポーネント `Dictionary`）再現。
/// </summary>
public class Dictionary
{
    public string Label { get; set; } = "";
}

/// <summary>同じ名前空間の非ジェネリック型。ゲートの過剰適用を確かめる対照。</summary>
public class Panel
{
    public string Title { get; set; } = "";
}

public class PanelHost
{
    // 宣言と同じ名前空間なので `using` がなくても結ばれる（= 消えてはいけないエッジ）
    public Panel Make() => new Panel();
}
