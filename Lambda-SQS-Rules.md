# Lambda → SQS 送信ガイドライン

このドキュメントではオンプレ側エージェントにリクエストを送信するために
AWS Lambda から SQS キューへメッセージを出す際の運用ルールと必要権限を
整理する。

---

## 1. 共通の設計方針

- メッセージは JSON 形式とし、必須項目として以下を含む。
  - `id`（UUID 等の一意識別子）
  - `sql`（実行する SQL 文）
  - `tns`（接続先データベース名）
  - `app_id`（ホワイトリスト登録済みアプリケーション ID）

- Lambda 関数はリクエスト ID を自前で生成し、レスポンス受信時にも同じ ID で照合する。
- エラー発生時は CloudWatch Logs に詳細を出力し、必要に応じて SNS を呼び出す。

---

## 2. 同一アカウント内からの送信

### 2.1 IAM ロールとポリシー

Lambda にアタッチする実行ロール例：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["sqs:SendMessage", "sqs:GetQueueUrl"],
      "Resource": "arn:aws:sqs:ap-northeast-1:<ACCOUNT_ID>:onprem-sql-request"
    }
  ]
}
```

- SQS キューのキューポリシーに同一アカウントの Lambda からの送信を許可する条項を
  設ける必要は基本的にない（ARN ベースでアクセス制限されているため）。

### 2.2 ネットワーク設定

- 同一アカウント内であれば通常のパブリックエンドポイントで問題ない。
- VPC 内からアクセスする場合は VPC エンドポイント（com.amazonaws.ap-northeast-1.sqs）を
  利用して内部トラフィックに抑える。

---

## 3. 異なるアカウントからの送信

### 3.1 Lambda 側の権限

送信元アカウントの Lambda 実行ロールには SQS への `SendMessage` 権限を付与する。

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["sqs:SendMessage", "sqs:GetQueueUrl"],
      "Resource": "arn:aws:sqs:ap-northeast-1:<TARGET_ACCOUNT_ID>:onprem-sql-request"
    }
  ]
}
```

### 3.2 受信側キューのキューポリシー

ターゲットアカウントの SQS キューには以下のようなポリシーを設定し、
送信元アカウントを明示的に許可する。

```json
{
  "Version": "2012-10-17",
  "Id": "CrossAccountSendPolicy",
  "Statement": [
    {
      "Sid": "AllowCrossAccountLambda",
      "Effect": "Allow",
      "Principal": {
        "AWS": "arn:aws:iam::<SOURCE_ACCOUNT_ID>:role/<LambdaExecutionRole>"
      },
      "Action": "sqs:SendMessage",
      "Resource": "arn:aws:sqs:ap-northeast-1:<TARGET_ACCOUNT_ID>:onprem-sql-request"
    }
  ]
}
```

※Lambda 関数が別アカウントから発行される場合、Principal を `AWS` ARN で指定するか、
`"AWS": "<SOURCE_ACCOUNT_ID>"` としてアカウント全体を許可してロール単位で制御する。

### 3.3 監査と CloudTrail

- クロスアカウント送信の場合、送信アカウント側と受信アカウント側の両方で
  CloudTrail による API ログを有効にし、送信操作が意図したものかを確認する。
- 必要に応じて CloudWatch アラームで異常な送信頻度やキューサイズ増加を監視。

---

## 4. セキュリティ上の注意点

- APP_ID ホワイトリストや SQL 検証は Lambda 側ではなく受信エージェント側でも
  再チェックする。送信元が信用できる場合でも防御的に検証を行う。
- メッセージペイロードに認証情報や機密データを含めない。ログに出力される可能性がある。
- SQS キューはパブリックサービスのため、IP 制限や VPC エンドポイントを併用すると
  より安全。

---

以上のルールを別ファイルとして管理することで Lambda 開発者が
SQS への依頼コードを書く際の手引きとする。
