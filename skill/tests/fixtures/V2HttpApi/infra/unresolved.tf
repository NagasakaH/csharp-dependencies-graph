# 所属が決まらない書き方。推測して同じ API にまとめないことの検査
variable "other_api_id" {
  type = string
}

resource "aws_apigatewayv2_api" "mystery" {
  name          = "mystery"
  protocol_type = "HTTP"
}

# `api_id` が `var` 越し（決まらない）
resource "aws_apigatewayv2_route" "via_var" {
  api_id    = var.other_api_id
  route_key = "PUT /v2/mystery"
  target    = "integrations/${aws_apigatewayv2_integration.create_item.id}"
}

# `api_id` が三項式（決まらない）
resource "aws_apigatewayv2_integration" "ternary" {
  api_id           = var.use_shop ? aws_apigatewayv2_api.shop.id : aws_apigatewayv2_api.partner.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_function.create_fn.arn
}

variable "use_shop" {
  type    = bool
  default = true
}

# `target` が混合補間（形が読めない）。縁を張らず `metadata.unresolved` に出す
resource "aws_apigatewayv2_route" "mixed_target" {
  api_id    = aws_apigatewayv2_api.shop.id
  route_key = "PATCH /v2/mixed"
  target    = "integrations/${aws_apigatewayv2_integration.create_item.id}/extra"
}

# `target` がこのビルドに無い integration を指す。存在しない先へ縁を張らない
resource "aws_apigatewayv2_route" "missing_target" {
  api_id    = aws_apigatewayv2_api.shop.id
  route_key = "TRACE /v2/missing"
  target    = "integrations/${aws_apigatewayv2_integration.nowhere.id}"
}
