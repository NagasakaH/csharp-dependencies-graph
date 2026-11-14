resource "aws_lambda_function" "valid" {
  handler = "RealAssembly::HandlerNs.A::Handle"
}

resource "aws_lambda_function" "without_assembly" {
  handler = "HandlerNs.A::Handle"
}

resource "aws_lambda_function" "nested" {
  handler = "RealAssembly::HandlerNs.A+Inner::Handle"
}

resource "aws_lambda_function" "other_type" {
  handler = "RealAssembly::HandlerNs.B::Handle"
}

resource "aws_lambda_function" "wrong_assembly" {
  handler = "OtherAssembly::HandlerNs.A::Handle"
}

resource "aws_lambda_function" "four_parts" {
  handler = "Extra::RealAssembly::HandlerNs.A::Handle"
}

resource "aws_lambda_function" "unknown_type" {
  handler = "RealAssembly::HandlerNs.Unknown::Handle"
}

data "aws_lambda_function" "existing" {
  handler = "RealAssembly::HandlerNs.A::Handle"
}
