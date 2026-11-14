# パスが**決まらない**書き方を集めた fixture。レポートは `POST /orders` の形で起点を引けるように
# `endpoint` を張るので、未解決の式から作ると実在しないパスを断定ことになる（いずれも出さない）

resource "aws_api_gateway_rest_api" "admin_api" {
  name = "admin"
}

# 親が `var` 参照。直下とも限らないのでパスは決まらない
variable "parent_id" { default = "x" }
resource "aws_api_gateway_resource" "var_parent" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = var.parent_id
  path_part   = "orders"
}
resource "aws_api_gateway_method" "var_parent_post" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = aws_api_gateway_resource.var_parent.id
  http_method = "POST"
}

# 親が module 出力
module "net" { source = "./net" }
resource "aws_api_gateway_resource" "module_parent" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = module.net.orders_resource_id
  path_part   = "sub"
}

# `for_each` のパス部品。値が一つに決まらない
resource "aws_api_gateway_resource" "each_part" {
  for_each    = toset(["a", "b"])
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = aws_api_gateway_rest_api.admin_api.root_resource_id
  path_part   = each.value
}
resource "aws_api_gateway_method" "each_get" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = aws_api_gateway_resource.each_part.id
  http_method = "GET"
}

# 補間で組み立てたパス部品
resource "aws_api_gateway_resource" "interp_part" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = aws_api_gateway_rest_api.admin_api.root_resource_id
  path_part   = "v${var.major}"
}

# HTTP API の route_key。`var.route_key` は未解決、`$default` は catch-all のリテラル
resource "aws_apigatewayv2_api" "http" { name = "http-api" }
variable "route_key" { default = "x" }
resource "aws_apigatewayv2_route" "var_key" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = var.route_key
}
resource "aws_apigatewayv2_route" "default_key" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "$default"
}

# 制御群: 正しく書けば決まる（上のどれかが張られていたら区別がつかない）
resource "aws_api_gateway_resource" "literal_ok" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = aws_api_gateway_rest_api.admin_api.root_resource_id
  path_part   = "health"
}

# 実プロジェクトの大半がこの書き方（単一の参照を補間しただけ）。
# 未解決の式を弾くときにこれも一緒に落すと、実在するエンドポイントが消える
resource "aws_api_gateway_resource" "quoted_ref" {
  rest_api_id = "${aws_api_gateway_rest_api.admin_api.id}"
  parent_id   = "${aws_api_gateway_rest_api.admin_api.root_resource_id}"
  path_part   = "quoted"
}

resource "aws_api_gateway_method" "quoted_get" {
  rest_api_id = "${aws_api_gateway_rest_api.admin_api.id}"
  resource_id = "${aws_api_gateway_resource.quoted_ref.id}"
  http_method = "GET"
}
