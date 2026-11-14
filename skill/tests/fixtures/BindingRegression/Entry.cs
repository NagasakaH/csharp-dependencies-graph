// グローバル名前空間の型とそのネスト型（同じファイルから見えるだけの参照を到達不能にしない）
public class Entry
{
    public void Run()
    {
        var inner = new Inner();
        inner.Go();
        try
        {
        }
        catch (BridgeRejectedException)
        {
        }
    }

    private class Inner
    {
        public void Go() { }
    }

    private class BridgeRejectedException : System.Exception { }
}
