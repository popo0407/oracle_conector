# Oracle SQL Bridge - デプロイメントガイド

このドキュメントは、AWS CDK スタック + オンプレミス Python エージェント の本番デプロイ手順を説明します。

## 目次

- [システム要件](#システム要件)
- [AWS 側セットアップ](#aws-側セットアップ)
- [オンプレ側セットアップ](#オンプレ側セットアップ)
- [サービス登録（Windows）](#サービス登録windows)
- [サービス登録（Linux/Mac）](#サービス登録linuxmac)
- [動作確認](#動作確認)
- [トラブルシューティング](#トラブルシューティング)
- [セキュリティチェックリスト](#セキュリティチェックリスト)

---

## システム要件

### AWS 側

- **AWS アカウント** (本番環境専用推奨)
- **AWS CLI v2** (認証・デプロイに使用)
- **Node.js 18+** (CDK 実行)
- **AWS CDK CLI** (`npm install -g aws-cdk`)
- **IAM ポリシー**: AdministratorAccess または下記リソースへのフル権限
  - CloudFormation
  - KMS
  - S3
  - SQS
  - SNS
  - IAM
  - Lambda
  - CloudWatch

### オンプレ側

| 項目             | 要件                                                                     |
| ---------------- | ------------------------------------------------------------------------ |
| **OS**           | Windows 10+ / Linux (CentOS 7+, Ubuntu 18.04+) / macOS 10.14+            |
| **Python**       | 3.8+ (推奨 3.11)                                                         |
| **Oracle ODBC**  | Oracle Instant Client (Basic + ODBC Supplement) または他の ODBC ドライバ |
| **ネットワーク** | AWS SQS へのアウトバウンド通信 (HTTPS 443)                               |
| **権限**         | サービス登録時に管理者権限が必要                                         |

---

## AWS 側セットアップ

### ステップ 1: AWS CLI で認証

```bash
aws sso login --profile your-profile
```

SSO ブラウザ認証を完了します。

### ステップ 2: 環境変数設定

```bash
export AWS_PROFILE=your-profile
export AWS_REGION=ap-northeast-1  # またはご利用のリージョン
```

### ステップ 3: CDK 初期化 (初回のみ)

```bash
cd aws
npm install
cdk bootstrap \
  --profile your-profile \
  --region ap-northeast-1
```

### ステップ 4: CDK スタックをデプロイ

```bash
cd aws
cdk deploy \
  --require-approval=never \
  --profile your-profile
```

**実行時間**: 5-10 分

**出力例**:

```
Outputs:
OnPremSqlBridgeStack.OnPremRoleArn = arn:aws:iam::XXXXXXXXXXXX:role/OnPremSqlBridgeRole
OnPremSqlBridgeStack.RequestQueueUrl = https://sqs.ap-northeast-1.amazonaws.com/XXXXXXXXXXXX/onprem-sql-request
OnPremSqlBridgeStack.ResponseQueueUrl = https://sqs.ap-northeast-1.amazonaws.com/XXXXXXXXXXXX/onprem-sql-response
OnPremSqlBridgeStack.ResultBucketName = onprem-sql-result-XXXXXXXXXXXX-ap-northeast-1
OnPremSqlBridgeStack.AlertTopicArn = arn:aws:sns:ap-northeast-1:XXXXXXXXXXXX:OnPremSqlBridgeAlerts
OnPremSqlBridgeStack.KmsCmkArn = arn:aws:kms:ap-northeast-1:XXXXXXXXXXXX:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

**これらの値をメモ** → オンプレ側の .env ファイルで使用します。

---

## オンプレ側セットアップ

### ステップ 1: リポジトリをクローン

```bash
git clone https://github.com/popo0407/oracle_conector.git
cd oracle_conector/onprem
```

### ステップ 2: Python 環境構築

#### Windows (PowerShell)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

#### Linux/macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### ステップ 3: 環境変数設定 (.env ファイル)

`.env.example` をコピーして `.env` を作成:

```bash
cp .env.example .env
```

**`.env` ファイルを編集**:

```dotenv
# AWS 設定（CDK 出力値を使用）
ROLE_ARN=arn:aws:iam::XXXXXXXXXXXX:role/OnPremSqlBridgeRole
REQUEST_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/XXXXXXXXXXXX/onprem-sql-request
RESPONSE_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/XXXXXXXXXXXX/onprem-sql-response
RESULT_BUCKET=onprem-sql-result-XXXXXXXXXXXX-ap-northeast-1
ALERT_TOPIC_ARN=arn:aws:sns:ap-northeast-1:XXXXXXXXXXXX:OnPremSqlBridgeAlerts
AWS_REGION=ap-northeast-1

# Oracle 設定
ORACLE_DSN=YOUR_ORACLE_DSN    # ODBC データソース名
ORACLE_USER=your_user         # Oracle ユーザー
ORACLE_PASSWORD=YourPassword  # Oracle パスワード

# その他
MOCK_MODE=false               # 本番の場合は false
LOG_LEVEL=INFO
ALLOWED_APP_IDS=app1,app2,app3
```

### ステップ 4: AWS IAM ロール認証設定

#### AWS SSO を使用する場合（推奨）

```bash
aws sso login --profile your-profile
```

#### AWS アクセスキーを使用する場合

```bash
aws configure --profile your-profile
```

**.aws/credentials** に設定されたプロフィール情報が使用されます。

### ステップ 5: テスト実行

```bash
python main.py
```

**ログ出力例** (成功):

```
2026-02-22 15:30:45,123 [INFO] __main__ - OnPrem SQL ブリッジ エージェントを起動します。
2026-02-22 15:30:45,150 [INFO] __main__ - 設定ロード: region=ap-northeast-1, ...
2026-02-22 15:30:47,820 [INFO] aws_client - STS AssumeRole 実行…
2026-02-22 15:30:50,456 [INFO] aws_client - STS セッション取得成功: 有効期限 2026-02-21T16:30:50+00:00 (UTC)
2026-02-22 15:30:50,460 [INFO] __main__ - 起動完了。SQS ポーリング中…
```

ログに `SQS ポーリング中` と表示されたら、**Ctrl+C で終了**。

⚠️ **MOCK_MODE=true での動作確認**（オプション）:

```bash
# .env を一時的に編集
MOCK_MODE=true

# テスト
python main.py

# SQS にメッセージ送信（別ターミナル）
python send_test_message.py
```

---

## サービス登録（Windows）

### 前提条件

- PowerShell を**管理者権限で実行**
- AWS SSO/IAM 認証が完了していること
- `.env` ファイルが正しく設定されていること

### 手順

#### 1. PowerShell 実行ポリシー設定 (初回のみ)

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

#### 2. サービスをインストール

```powershell
cd C:\path\to\oracle_conector\scripts

# 基本的なインストール
.\register-service-windows.ps1 `
  -ServiceName "OnPremSqlBridge" `
  -AgentPath "C:\path\to\oracle_conector\onprem" `
  -Action Install
```

#### 3. サービスを開始

```powershell
.\register-service-windows.ps1 `
  -ServiceName "OnPremSqlBridge" `
  -Action Start
```

#### 4. ステータス確認

```powershell
# サービスステータス確認
Get-Service OnPremSqlBridge

# イベントログ確認
Get-EventLog -LogName Application | Where-Object {$_.Source -like '*OnPremSqlBridge*'} | Select-Object -First 20
```

### トラブルシューティング

**サービスが起動しない場合**:

```powershell
# ステータス確認
Get-Service OnPremSqlBridge

# イベントログ詳細確認
Get-EventLog -LogName Application | Where-Object {$_.Source -like '*OnPremSqlBridge*'} | Format-List -Property * | Head -50

# サービス削除と再インストール
.\register-service-windows.ps1 -ServiceName "OnPremSqlBridge" -Action Uninstall
.\register-service-windows.ps1 -ServiceName "OnPremSqlBridge" -AgentPath "C:\path\to\oracle_conector\onprem" -Action Install
```

---

## サービス登録（Linux/Mac）

### 前提条件

- `sudo` ユーザーであること
- Python 3 がインストール済み
- AWS IAM/SSO 認証が完了していること
- `.env` ファイルが正しく設定されていること

### 手順

#### 1. スクリプトに実行権限を付与

```bash
chmod +x scripts/register-service-linux.sh
```

#### 2. サービスをインストール

```bash
sudo bash scripts/register-service-linux.sh \
  --install \
  --agent-path ~/oracle_conector/onprem \
  --service-user $USER
```

#### 3. 自動起動を有効化

```bash
sudo systemctl enable onprem-sql-bridge
```

#### 4. サービスを開始

```bash
sudo systemctl start onprem-sql-bridge
```

#### 5. ステータス確認

```bash
# サービスステータス確認
sudo systemctl status onprem-sql-bridge

# ログ確認
sudo journalctl -u onprem-sql-bridge -f
```

### 便利なコマンド

```bash
# サービス再起動
sudo systemctl restart onprem-sql-bridge

# サービス停止
sudo systemctl stop onprem-sql-bridge

# 最新 50 行のログ表示
sudo journalctl -u onprem-sql-bridge -n 50

# リアルタイムログ（Tail）
sudo journalctl -u onprem-sql-bridge -f

# 特定の日時以降のログ
sudo journalctl -u onprem-sql-bridge --since "2 hours ago"
```

---

## 動作確認

### 1. ローカルテスト（サービス起動前）

```bash
cd onprem
python main.py
```

**期待される出力**:

- ✅ STS AssumeRole 完了
- ✅ SQS ポーリング開始

**Ctrl+C で終了**。

### 2. SQS メッセージ送信テスト

#### Python スクリプトで送信

```bash
python send_test_message.py
```

#### AWS CLI で送信

```bash
TIMESTAMP=$(date +%s%N | cut -b1-13)
aws sqs send-message \
  --queue-url "https://sqs.ap-northeast-1.amazonaws.com/XXXXXXXXXXXX/onprem-sql-request" \
  --message-body '{
    "id": "test-'$TIMESTAMP'",
    "sql": "SELECT * FROM orders WHERE MK_DATE BETWEEN TO_DATE('"'"'2024-01-01'"'"','"'"'YYYY-MM-DD'"'"') AND TO_DATE('"'"'2024-12-31'"'"','"'"'YYYY-MM-DD'"'"')",
    "tns": "YOUR_TNS_NAME",
    "app_id": "app1"
  }'
```

### 3. S3 結果確認

```bash
# ファイル一覧
aws s3 ls s3://onprem-sql-result-XXXXXXXXXXXX-ap-northeast-1/

# 最新結果をダウンロード・表示
aws s3 cp s3://onprem-sql-result-XXXXXXXXXXXX-ap-northeast-1/$(
  aws s3 ls s3://onprem-sql-result-XXXXXXXXXXXX-ap-northeast-1/ | tail -1 | awk '{print $4}'
) - | jq .
```

---

## トラブルシューティング

### AWS 認証エラー

**エラー**: `Unable to locate credentials`

**対策**:

```bash
# SSO ログイン
aws sso login --profile your-profile

# またはアクセスキーを設定
aws configure --profile your-profile
```

### Python パッケージのインストールエラー

**エラー**: `ModuleNotFoundError: No module named 'pyodbc'`

**対策**:

```bash
pip install --upgrade pip setuptools
pip install -r requirements.txt
```

### Oracle ODBC 接続エラー

**エラー**: `pyodbc.InterfaceError: ('01000', "[01000] [unixODBC][Driver Manager]...`

**対策**:

1. ODBC ドライバのインストール確認

   ```bash
   odbcinst -j  # ドライバ情報表示
   ```

2. DSN 確認

   ```bash
   odbcinst -l -d  # インストール済みドライバ一覧
   ```

3. テスト接続
   ```bash
   python -c "import pyodbc; print(pyodbc.drivers())"
   ```

### SQS 接続エラー

**エラー**: `An error occurred (InvalidSignatureException)`

**対策**:

1. AWS 認証状態確認

   ```bash
   aws sts get-caller-identity
   ```

2. .env ファイルの `ROLE_ARN` を確認

3. IAM ポリシー確認（SQS:SendMessage, SQS:ReceiveMessage 権限）

### ログファイル確認

```bash
# Linux/Mac
tail -f onprem_sql_bridge.log

# Windows PowerShell
Get-Content onprem_sql_bridge.log -Tail 50 -Wait
```

---

## セキュリティチェックリスト

本番運用前に以下を確認してください。

### AWS 側

- [ ] KMS CMK が `kms:ViaService` で S3・SQS に限定されている
- [ ] S3 バケットが**プライベート（パブリックアクセス禁止）**に設定
- [ ] S3 バケットで **SSE-KMS** 暗号化有効
- [ ] S3 バケットで **HTTPS 強制** (DenyNonSsl)
- [ ] SQS キューで **長期 VPC エンドポイント** 検討
- [ ] SNS トピックで認可ポリシーを確認
- [ ] IAM ロール AssumeRole の信頼ポリシーを確認
- [ ] CloudWatch アラームが動作している

### オンプレミス側

- [ ] `.env` ファイルのパスワード/シークレットは **gitignore に追加**
- [ ] Oracle パスワードは **AWS Secrets Manager に移行**（本番）
- [ ] ログファイル (`onprem_sql_bridge.log`) は機密データがないことを確認
- [ ] ファイアウォール: **AWS SQS (HTTPS 443) へのアウトバウンド許可**
- [ ] ウイルススキャン: オンプレ PC でスキャン実施
- [ ] セキュリティ設定: `python -m pip install pipdeptree` で依存関係を確認

### 全体

- [ ] 暗号化: SQS (At-Rest KMS), S3 (SSE-KMS), KMS (自動ローテーション)
- [ ] アクセス制御: 最小権限の原則（AWS IAM ロール）
- [ ] 監査ログ: CloudTrail で API 呼び出し記録
- [ ] ネットワーク: VPC エンドポイント、プライベートリンク検討

---

## まとめ

| 項目                 | AWS 側          | オンプレ側         |
| -------------------- | --------------- | ------------------ |
| **セットアップ時間** | 15 分           | 10 分              |
| **テスト実行時間**   | 5 分            | 5 分               |
| **月次保守**         | CloudWatch 監視 | ログ確認、更新確認 |

質問・問題発生時:

- [GitHub Issues](https://github.com/popo0407/oracle_conector/issues) にご報告ください
- AWS サポート窓口へ (AWS 側の問題の場合)
- Linux/Mac でのトラブルは環境依存の可能性があります

---

_最終更新: 2026-02-22_
