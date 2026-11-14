# 別 API が同じ Lambda を共有する配置。兄弟として区別し、起点の「同じ API の定義」に混ぜない
resource "aws_apigatewayv2_api" "partner" {
  name          = "partner-http"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "partner_integ" {
  api_id           = aws_apigatewayv2_api.partner.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.ref.lambda_arn
}

resource "aws_lambda_function" "ref" {
  function_name = "partner-ref"
  handler       = "ShopAssembly::Shop.Orders::Shared"
  role          = aws_iam_role.shop_role.arn
}

resource "aws_apigatewayv2_route" "partner_route" {
  api_id    = aws_apigatewayv2_api.partner.id
  route_key = "GET /v2/partner"
  target    = "integrations/${aws_apigatewayv2_integration.partner_integ.id}"
}

# IAM ロールだけを共有する別 Lambda。`references` で繋がるだけで本命にしてはいけない
resource "aws_lambda_function" "unrelated" {
  function_name = "unrelated"
  handler       = "ShopAssembly::Shop.Orders::Shared"
  role          = aws_iam_role.shop_role.arn
}

# WebSocket の eventId のみの route。HTTP のパスとして捏造しない
resource "aws_apigatewayv2_api" "ws" {
  name          = "shop-ws"
  protocol_type = "WEBSOCKET"
}

resource "aws_apigatewayv2_route" "connect" {
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = "$connect"
}
