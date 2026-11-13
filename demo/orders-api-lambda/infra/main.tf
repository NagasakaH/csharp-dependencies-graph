terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "ap-northeast-1"
}

locals {
  orders_table = "orders"
}

resource "aws_dynamodb_table" "orders" {
  name         = local.orders_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "Id"
}

resource "aws_iam_role" "lambda_role" {
  name = "orders-lambda-role"
}

resource "aws_iam_role_policy" "lambda_dynamo_policy" {
  role   = aws_iam_role.lambda_role.id
  policy = jsonencode({ Statement = [{ Action = ["dynamodb:*"], Resource = aws_dynamodb_table.orders.arn }] })
}

resource "aws_lambda_function" "orders_api" {
  function_name = "orders-api"
  handler       = "Orders.Api::Orders.Api.Functions::CreateOrder"
  runtime       = "dotnet8"
  memory_size   = 512
  role          = aws_iam_role.lambda_role.arn
  filename      = "dist/Orders.Api.zip"
  environment {
    variables = { ORDERS_TABLE = aws_dynamodb_table.orders.name }
  }
}

resource "aws_lambda_function" "notify" {
  function_name = "orders-notify"
  handler       = "Orders.Infrastructure::Orders.Infrastructure.NotifyHandler::FunctionHandler"
  runtime       = "dotnet8"
  role          = aws_iam_role.lambda_role.arn
  filename      = "dist/Orders.Infrastructure.zip"
  environment {
    variables = { FULFIL_QUEUE_URL = aws_sqs_queue.fulfilment.url, ORDERS_TABLE = aws_dynamodb_table.orders.name }
  }
}

resource "aws_sfn_state_machine" "order_process" {
  name     = "order-process"
  role_arn = aws_iam_role.lambda_role.arn
  definition = jsonencode({
    Comment = "order process"
    States  = {
      Notify = {
        Type     = "Task"
        Resource = aws_lambda_function.notify.arn
      }
    }
  })
}

resource "aws_sqs_queue" "fulfilment" {
  name = "orders-fulfilment"
}

resource "aws_sns_topic" "order_events" {
  name = "order-events"
}

resource "aws_api_gateway_rest_api" "orders" {
  name = "orders-api-gateway"
}

resource "aws_api_gateway_resource" "orders_path" {
  rest_api_id = aws_api_gateway_rest_api.orders.id
  parent_id   = aws_api_gateway_rest_api.orders.root_resource_id
  path_part   = "orders"
}

resource "aws_api_gateway_method" "post_order" {
  rest_api_id   = aws_api_gateway_rest_api.orders.id
  resource_id   = aws_api_gateway_resource.orders_path.id
  http_method   = "POST"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "post_order" {
  rest_api_id             = aws_api_gateway_rest_api.orders.id
  resource_id             = aws_api_gateway_resource.orders_path.id
  http_method             = aws_api_gateway_method.post_order.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.orders_api.invoke_arn
}

resource "aws_api_gateway_method" "get_order" {
  rest_api_id   = aws_api_gateway_rest_api.orders.id
  resource_id   = aws_api_gateway_resource.orders_path.id
  http_method   = "GET"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "get_order" {
  rest_api_id             = aws_api_gateway_rest_api.orders.id
  resource_id             = aws_api_gateway_resource.orders_path.id
  http_method             = aws_api_gateway_method.get_order.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.orders_api.invoke_arn
}

resource "aws_api_gateway_deployment" "live" {
  rest_api_id = aws_api_gateway_rest_api.orders.id
  triggers = {
    post = aws_api_gateway_integration.post_order.id
    get  = aws_api_gateway_integration.get_order.id
  }
}

output "api_endpoint" {
  value = aws_api_gateway_deployment.live.id
}
