# module をまたぐと同じローカルアドレスを使い得る。id が衝突すると片方の endpoint が黙って消える
resource "aws_api_gateway_rest_api" "api" { name = "two" }
resource "aws_api_gateway_resource" "path" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  parent_id   = aws_api_gateway_rest_api.api.root_resource_id
  path_part   = "two"
}
resource "aws_api_gateway_method" "get" {
  rest_api_id = aws_api_gateway_rest_api.api.id
  resource_id = aws_api_gateway_resource.path.id
  http_method = "GET"
}
