namespace Shop;

// HTTP API（`aws_apigatewayv2_*`）の route から Lambda、Lambda の handler 経由でこのメソッドまで
// 「本命」として届くことを検査するための fixture。注釈（`llm` / `human`）は無しが前提
public class Orders
{
    // `POST /v2/items` の実装（起点の実装）
    public void Create()
    {
        Shared();
    }

    // 同じ API の**別の route** の実装。`api_id` が同じというだけで起点の実装にしてはいけない
    public void Cancel()
    {
        Shared();
    }

    // 両方から呼ばれる共通処理（起点の実装から届くのはこちら側）
    public void Shared() { }
}
