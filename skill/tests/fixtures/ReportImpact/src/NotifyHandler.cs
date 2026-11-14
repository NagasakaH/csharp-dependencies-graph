// OrderHandler.cs と同じフォルダにあるだけの**無関係なファイル**。
// 変更ファイル起点が階層で兄弟を巻き込まないことを照合する（依存縁は 1 本も無い）
namespace ReportImpact;

public class Notify
{
    public static string Send(string text) => text;
}
