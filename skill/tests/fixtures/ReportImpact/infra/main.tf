# 変更ファイル → Lambda → API Gateway の経路と、Terraform の `references` だけの定義単位を両方置く。
resource "aws_api_gateway_rest_api" "orders_api" {
  name = "orders-api"
}

resource "aws_api_gateway_resource" "orders" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  parent_id   = aws_api_gateway_rest_api.orders_api.root_resource_id
  path_part   = "orders"
}

resource "aws_api_gateway_method" "post_order" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  resource_id = aws_api_gateway_resource.orders.id
  http_method = "POST"
}

# 同じ Lambda を使う別エンドポイント（兄弟エンドポイントとして別枠に出るべきもの）
resource "aws_api_gateway_method" "get_order" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  resource_id = aws_api_gateway_resource.orders.id
  http_method = "GET"
}

resource "aws_api_gateway_integration" "post_order" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  resource_id = aws_api_gateway_resource.orders.id
  uri         = aws_lambda_function.orders_api.invoke_arn
}

resource "aws_api_gateway_deployment" "live" {
  rest_api_id = aws_api_gateway_rest_api.orders_api.id
  stage_name  = "prod"
}

resource "aws_lambda_function" "orders_api" {
  function_name = "orders-api"
  handler       = "ReportImpact::ReportImpact.Handler::Handle"
  role          = aws_iam_role.lambda_role.arn
}

resource "aws_dynamodb_table" "orders" {
  name = "orders"
}

resource "aws_iam_role" "lambda_role" {
  name = "lambda-role"
}

resource "aws_iam_role_policy" "dynamo_policy" {
  role   = aws_iam_role.lambda_role.id
  policy = aws_dynamodb_table.orders.name
}

data "aws_caller_identity" "current" {}
# data ソースはほとんどを参照してノイズになるので、レポートは既定で閉じない（`--include-data` で出す）
resource "aws_lambda_function" "notify" {
  function_name    = "notify"
  handler          = "ReportImpact::ReportImpact.Notify::Send"
  source_code_hash = data.aws_caller_identity.current.account_id
}

# --- 別 API（admin）。**同じ Lambda を共有する**ので「起点と同じ API」ではない。
# 既定の段数（3）で見えることを検査で固定する（昔は 6 段上げても別 API が消えた） ---
resource "aws_api_gateway_rest_api" "admin_api" {
  name = "admin-api"
}

resource "aws_api_gateway_resource" "admin_users" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  parent_id   = aws_api_gateway_rest_api.admin_api.root_resource_id
  path_part   = "users"
}

resource "aws_api_gateway_method" "get_users" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = aws_api_gateway_resource.admin_users.id
  http_method = "GET"
}

resource "aws_api_gateway_integration" "get_users" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  resource_id = aws_api_gateway_resource.admin_users.id
  uri         = aws_lambda_function.orders_api.invoke_arn
}

resource "aws_api_gateway_deployment" "admin_live" {
  rest_api_id = aws_api_gateway_rest_api.admin_api.id
  stage_name  = "admin"
}
