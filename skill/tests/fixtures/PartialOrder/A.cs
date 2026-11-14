namespace Fix.Partial;

// partial の別ファイルにある同名オーバーロードは同じ member ID に畳まれる。
// 同じ edge ID に別の行が届くので、代表位置を決定できないと出力が揺れる（第 11 ラウンドの P2）
public partial class C
{
    public void Run() { Target.Go(); }
}

public static class Target
{
    public static void Go() { }
}
