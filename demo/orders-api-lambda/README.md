# orders-api-lambda

AWS Lambda (.NET 8) を Terraform で管理するデモプロジェクト。

- `src/Orders.Api` — API Gateway から呼び出される Lambda ハンドラ
- `src/Orders.Infrastructure` — DynamoDB / Step Functions / SQS へのアクセス
- `infra/main.tf` — Lambda・Step Functions・API Gateway・DynamoDB・SQS・SNS の定義

C# 側は `csproj` と `Lambda` SDK の参照までを静的解析で拾い、
どの Lambda 関数・どのテーブルに対応するかは注釈（annotations.json）で紐づける。
