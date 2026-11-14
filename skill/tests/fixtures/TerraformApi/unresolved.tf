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
resource "aws_apigatewayv2_api" "http_unresolved" { name = "http-api" }
variable "route_key" { default = "x" }
resource "aws_apigatewayv2_route" "var_key" {
  api_id    = aws_apigatewayv2_api.http_unresolved.id
  route_key = var.route_key
}
resource "aws_apigatewayv2_route" "default_key" {
  api_id    = aws_apigatewayv2_api.http_unresolved.id
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

# 式の途中に正しい参照が含まれていても、**値全体がその形でなければ未解決**とする。
# 部分一致で判定していた頃は、これらから実在しない `GET /orders` が生まれていた
variable "suffix" { default = "x" }
variable "verb" { default = "GET" }
resource "aws_api_gateway_resource" "cond_parent" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = var.use_root ? aws_api_gateway_rest_api.admin_api.root_resource_id : aws_api_gateway_resource.literal_ok.id
  path_part   = "cond"
}
resource "aws_api_gateway_resource" "join_parent" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = join("", [aws_api_gateway_rest_api.admin_api.root_resource_id, var.suffix])
  path_part   = "joined"
}
resource "aws_api_gateway_resource" "mixed_interp_parent" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = "${aws_api_gateway_rest_api.admin_api.root_resource_id}-${var.suffix}"
  path_part   = "mixed"
}
# 値が分からない**他のリソースの属性**を path_part に置いてもパスにはしない
resource "aws_api_gateway_resource" "ssm_part" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = aws_api_gateway_rest_api.admin_api.root_resource_id
  path_part   = aws_ssm_parameter.segment.value
}
# 逆に、引用されたリテラルは**点を含んでいてもリテラル**なので決まる
resource "aws_api_gateway_resource" "dotted_literal" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = aws_api_gateway_rest_api.admin_api.root_resource_id
  path_part   = "local.segment"
}
resource "aws_api_gateway_method" "dotted_get" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = aws_api_gateway_resource.dotted_literal.id
  http_method = "GET"
}
# `resource_id` と `http_method` が未解決なら endpoint を張らない（パスだけは決まる）
resource "aws_api_gateway_method" "cond_id" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = var.use_root ? aws_api_gateway_resource.literal_ok.id : var.other_resource_id
  http_method = "POST"
}
resource "aws_api_gateway_method" "cond_verb" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = aws_api_gateway_resource.literal_ok.id
  http_method = var.verb
}
# `count` の添字は同じパスのインスタンスなので解決してよい
resource "aws_api_gateway_resource" "counted_base" {
  count       = 2
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = aws_api_gateway_rest_api.admin_api.root_resource_id
  path_part   = "base"
}
resource "aws_api_gateway_method" "counted_get" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = aws_api_gateway_resource.counted_base[0].id
  http_method = "GET"
}
