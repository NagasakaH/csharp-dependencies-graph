namespace Fix.Regress.Boxes;

// 名前空間 `Fix.Regress.Boxes` の方だけジェネリック。使用側が `<int>` と書いていれば
// 型パラメータ数の違う同名型（`Fix.Regress.Handlers.Box`）を飛ばしてここへ辿り着く
public class Box<T>
{
    public T Value { get; set; } = default!;

    public void Go() { }
}
