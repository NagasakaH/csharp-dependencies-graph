resource "aws_sfn_state_machine" "a" {
  name = "a"
  role_arn = var.role_arn
  definition = jsonencode({ StartAt = "D", States = { D = { Type = "Task", Resource = aws_lambda_function.d.arn, End = true } } })
}
resource "aws_sfn_state_machine" "b" {
  name = "b"
  role_arn = var.role_arn
  definition = jsonencode({ StartAt = "D", States = { D = { Type = "Task", Resource = aws_lambda_function.d.arn, Next = "E" }, E = { Type = "Task", Resource = aws_lambda_function.e.arn, End = true } } })
}
resource "aws_sfn_state_machine" "c" {
  name = "c"
  role_arn = var.role_arn
  tags = { RelatedWorkflow = aws_sfn_state_machine.a.name }
  definition = jsonencode({ StartAt = "E", States = { E = { Type = "Task", Resource = aws_lambda_function.e.arn, End = true } } })
}
resource "aws_lambda_function" "d" {
  function_name = "d"
}
resource "aws_lambda_function" "e" {
  function_name = "e"
}
