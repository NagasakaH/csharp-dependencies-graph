# HTTP API（v2）。`route` は `target` で `integration` に委譲し、`integration` は `integration_uri`
# で Lambda を指す。`api_id` が同じ API の所属を決める根拠になる
resource "aws_apigatewayv2_api" "shop" {
  name          = "shop-http"
  protocol_type = "HTTP"
}

resource "aws_lambda_function" "create_fn" {
  function_name = "shop-create"
  handler       = "ShopAssembly::Shop.Orders::Create"
  role          = aws_iam_role.shop_role.arn
}

resource "aws_apigatewayv2_integration" "create_item" {
  api_id           = aws_apigatewayv2_api.shop.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.create_fn.arn
}

resource "aws_apigatewayv2_route" "create" {
  api_id    = aws_apigatewayv2_api.shop.id
  route_key = "POST /v2/items"
  target    = "integrations/${aws_apigatewayv2_integration.create_item.id}"
}

# 同じ API の同じ integration を使う別の route（共有実装）。兄弟エンドポイント側に出る
resource "aws_apigatewayv2_route" "cancel_same" {
  api_id    = aws_apigatewayv2_api.shop.id
  route_key = "DELETE /v2/items/{id}/cancel"
  target    = "integrations/${aws_apigatewayv2_integration.create_item.id}"
}

# 同じ API の**別の route が別の Lambda を使う**配置。`api_id` が同じだけで本命にしてはいけない
resource "aws_lambda_function" "cancel_fn" {
  function_name = "shop-cancel"
  handler       = "ShopAssembly::Shop.Orders::Cancel"
  role          = aws_iam_role.shop_role.arn
}

resource "aws_apigatewayv2_integration" "cancel_item" {
  api_id           = aws_apigatewayv2_api.shop.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.cancel_fn.arn
}

resource "aws_apigatewayv2_route" "cancel_other" {
  api_id    = aws_apigatewayv2_api.shop.id
  route_key = "DELETE /v2/orders/{id}"
  target    = "integrations/${aws_apigatewayv2_integration.cancel_item.id}"
}

resource "aws_apigatewayv2_stage" "live" {
  api_id      = aws_apigatewayv2_api.shop.id
  name        = "$default"
  auto_deploy = true
}

resource "aws_apigatewayv2_deployment" "d1" {
  api_id = aws_apigatewayv2_api.shop.id
}

# catch-all の route は実在する HTTP パスではない（`endpoint` を張らない）
resource "aws_apigatewayv2_route" "fallback" {
  api_id    = aws_apigatewayv2_api.shop.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.create_item.id}"
}

resource "aws_iam_role" "shop_role" {
  name = "shop-role"
}
