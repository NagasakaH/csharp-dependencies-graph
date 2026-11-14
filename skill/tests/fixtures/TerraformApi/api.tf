# レポートが「POST /orders」のように HTTP のメソッドとパスで起点を引けるように、
# `path_part` と `parent_id` からパスを組み立てることを検査する Terraform だけの fixture。
resource "aws_api_gateway_rest_api" "orders_api" {
  name = "orders-api"
}

resource "aws_api_gateway_resource" "orders" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  parent_id   = aws_api_gateway_rest_api.orders_api.root_resource_id
  path_part   = "orders"
}

# 親が rest_api の root でない入れ子リソース（`/orders/{id}` になる）
resource "aws_api_gateway_resource" "orders_item" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  parent_id   = aws_api_gateway_resource.orders.id
  path_part   = "{id}"
}

resource "aws_api_gateway_method" "post_order" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  resource_id = aws_api_gateway_resource.orders.id
  http_method = "POST"
}

resource "aws_api_gateway_method" "get_item" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  resource_id = aws_api_gateway_resource.orders_item.id
  http_method = "GET"
}

resource "aws_api_gateway_deployment" "live" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  stage_name  = "prod"
}

# HTTP API（v2）は route_key にメソッドとパスが入っている
resource "aws_apigatewayv2_api" "http" {
  name          = "orders-http"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_route" "cancel" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "DELETE /orders/{id}/cancel"
}

data "aws_caller_identity" "current" {}

# `resource_id` が無いメソッドにはパスを作れない。推測して `endpoint` を張らないことの検査
resource "aws_api_gateway_method" "orphan" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  http_method = "DELETE"
}

# `parent_id` が循環している（HCL としては不正だが、解析側で無限再帰しないことを見る）
resource "aws_api_gateway_resource" "loop_a" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  parent_id   = aws_api_gateway_resource.loop_b.id
  path_part   = "a"
}

resource "aws_api_gateway_resource" "loop_b" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  parent_id   = aws_api_gateway_resource.loop_a.id
  path_part   = "b"
}
