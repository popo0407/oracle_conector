# OnPrem Oracle SQL Bridge

オンプレミス Oracle DB に対して AWS 側から SQL を安全に実行するためのブリッジシステムです。

---

## アーキテクチャ概要

```
┌──────────────────────────────────────────────────────────────┐
│ AWS                                                          │
│                                                              │
│  Lambda                                                      │
│  (RequestSender)  ──SendMessage──►  SQS Request Queue       │
│                                          │                   │
│  Lambda / API GW  ◄─ReceiveMessage──  SQS Response Queue    │
│                                          │                   │
│  S3 Result Bucket ◄───── PutObject ──────┤                   │
│                                          │                   │
│  SNS Alert Topic  ◄────── Publish ───────┤                   │
└──────────────────────────────────────────┼───────────────────┘
                                           │ HTTPS (Proxy)
                                           ▼
                            ┌──────────────────────────┐
                            │ ON-PREMISE HOST          │
                            │  Python Agent (main.py)  │
                            │  - STS AssumeRole        │
                            │  - SQS Long Polling      │
                            │  - SQL Validation        │
                            │  - ODBC → Oracle 18c     │
                            └──────────────────────────┘
```

---

## ディレクトリ構成

```
ORACLE_CONECTER/
├── aws/                         # AWS CDK プロジェクト（TypeScript）
│   ├── bin/
│   │   └── app.ts               # CDK エントリーポイント
│   ├── lib/
│   │   └── on-prem-sql-bridge-stack.ts  # メインスタック定義
│   ├── lambda/
│   │   └── request-sender/
│   │       ├── index.ts         # SQL リクエスト送信 Lambda
│   │       └── package.json
│   ├── cdk.json
│   ├── package.json
│   └── tsconfig.json
│
├── onprem/                      # オンプレミス Python エージェント
│   ├── main.py                  # メインループ
│   ├── config.py                # 設定管理
│   ├── aws_client.py            # AWS クライアント（STS/SQS/S3/SNS）
│   ├── oracle_client.py         # Oracle ODBC クライアント
│   ├── sql_validator.py         # SQL バリデーション
│   ├── requirements.txt
│   ├── .env.example
│   └── onprem-sql-bridge.service  # systemd ユニットファイル
│
└── docs/
    └── retrospective.md
```

---

## AWS 側セットアップ

### 前提条件

- Node.js 22.x 以上
- AWS CDK v2
- AWS CLI 設定済み（デプロイ権限あり）

### インストール＆デプロイ

```bash
cd aws
npm install

# CDK ブートストラップ（初回のみ）
npx cdk bootstrap

# テンプレート確認
npx cdk synth

# デプロイ
npx cdk deploy
```

### CDK コンテキスト変数

| 変数名 | 説明 | デフォルト |
|---|---|---|
| `allowedOnPremIp` | SQS IP 制限に使用するオンプレ固定 IP | `203.0.113.10/32` |
| `enableLambdaSender` | Lambda リクエスト送信機能を有効化 | `true` |

```bash
npx cdk deploy --context allowedOnPremIp=<YOUR_IP>/32
```

### デプロイ後に確認する出力値

| 出力キー | 用途 |
|---|---|
| `RequestQueueUrl` | オンプレ側 `REQUEST_QUEUE_URL` に設定 |
| `ResponseQueueUrl` | オンプレ側 `RESPONSE_QUEUE_URL` に設定 |
| `ResultBucketName` | オンプレ側 `RESULT_BUCKET` に設定 |
| `OnPremRoleArn` | オンプレ側 `ROLE_ARN` に設定 |
| `AlertTopicArn` | オンプレ側 `ALERT_TOPIC_ARN` に設定 |

---

## オンプレミス側セットアップ

### 前提条件

- Python 3.11 以上
- Oracle 18c ODBC ドライバ（64bit）インストール済み
- ODBC データソース（DSN）設定済み
- AWS CLI 認証情報（IAM ユーザー権限: `sts:AssumeRole` のみ）

### インストール

```bash
cd onprem
python -m venv venv
venv\Scripts\activate       # Windows
# または source venv/bin/activate  # Linux

pip install -r requirements.txt
```

### 環境変数設定

```bash
cp .env.example .env
# .env を編集して CDK デプロイ後の値を設定
```

### 起動

```bash
python main.py
```

### systemd での常駐化（Linux）

```bash
sudo cp onprem-sql-bridge.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable onprem-sql-bridge
sudo systemctl start onprem-sql-bridge
sudo systemctl status onprem-sql-bridge
```

---

## SQS メッセージフォーマット

### リクエスト（Request Queue）

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "sql": "SELECT order_id, amount FROM orders WHERE mk_date BETWEEN '2025-01-01' AND '2025-01-31'",
  "tns": "ORCL_PROD",
  "app_id": "app1"
}
```

| フィールド | 必須 | 説明 |
|---|---|---|
| `id` | ✅ | UUID 等の一意識別子 |
| `sql` | ✅ | 実行する SQL 文 |
| `tns` | ✅ | 接続先 Oracle TNS 名 |
| `app_id` | ✅ | ホワイトリスト登録済みアプリ ID |

### レスポンス（Response Queue）

**SELECT 成功時:**
```json
{"id": "550e8400-...", "s3_key": "550e8400-....json"}
```

**DML 成功時:**
```json
{"id": "550e8400-...", "affected_rows": 1}
```

**エラー時:**
```json
{"id": "550e8400-...", "error": "エラーメッセージ"}
```

---

## SQL 制約

| 種別 | 制約 |
|---|---|
| SELECT | `WHERE` 句と `MK_DATE BETWEEN` 指定が必須 |
| INSERT / UPDATE | 影響行数が 1 行のみ許可 |
| DELETE / DROP 等 | 一切禁止 |

---

## セキュリティ設計

| 項目 | 実装内容 |
|---|---|
| 認証 | STS AssumeRole（短期クレデンシャル、1時間） |
| 暗号化 | KMS CMK（`kms:ViaService` で S3/SQS 経由のみ許可） |
| 転送暗号化 | S3・SQS ともに HTTPS 強制（`DenyNonSsl`） |
| ネットワーク | SQS キューポリシーでオンプレ固定 IP のみ許可 |
| 最小権限 | IAM ロールは必要アクションのみ許可 |
| データ保持 | S3 Lifecycle 7日後自動削除 |
| 障害通知 | DLQ 増加・キュー滞留で SNS アラート |

---

## 監視・運用

- **CloudWatch アラーム**
  - DLQ メッセージ数 ≥ 1 → SNS 通知
  - リクエストキュー最古メッセージ滞留 ≥ 5分 → SNS 通知

- **エージェントログ**
  - `onprem_sql_bridge.log`（同ディレクトリに出力）
  - `LOG_LEVEL` 環境変数でレベル制御可能

---

## ネットワーク事前確認

オンプレ PC からの疎通確認は [オンプレPC確認事項.md](オンプレPC確認事項.md) を参照してください。

---

## 参考資料

- [設計書.md](設計書.md)
- [CDK+Cloudformation.md](CDK+Cloudformation.md)
- [オンプレ側システム参考.md](オンプレ側システム参考.md)
- [Lambda-SQS-Rules.md](Lambda-SQS-Rules.md)
