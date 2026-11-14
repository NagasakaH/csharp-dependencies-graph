using Fix.TupleArg.Models;

namespace Fix.TupleArg.Wrong;

/// <summary>別名前空間にある同じ名前の非ジェネリック。型引数ゲートが正しく数えていれば
/// ここには張らない（同名でも型引数の数が違う候補は飛ばして次に進む）。
/// 同じ名前空間に置くと `Box` と `Box<T>` のノード ID が同じになり区別できないため、
/// わざと名前空間を分けてある。</summary>
public class Box
{
    public Item Next => new Item();
    public Item MakeItem() => new Item();
}
