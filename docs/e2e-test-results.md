# E2E テスト結果 (2026-02-22)

## テスト概要

MOCK_MODE=true の状態でシステム全体の SQS → オンプレエージェント → S3 フローを検証しました。

---

## テスト手順

### 1. エージェント起動

`.env` ファイルに CDK デプロイ値を設定：
```env
ROLE_ARN=arn:aws:iam::590184009554:role/OnPremSqlBridgeRole
REQUEST_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/590184009554/onprem-sql-request
RESPONSE_QUEUE_URL=https://sqs.ap-northeast-1.amazonaws.com/590184009554/onprem-sql-response
RESULT_BUCKET=onprem-sql-result-590184009554-ap-northeast-1
AWS_REGION=ap-northeast-1
MOCK_MODE=true
ALLOWED_APP_IDS=app1,app2,app3
```

`main.py` に `load_dotenv()` を追加し、Python エージェントをバックグラウンド実行

### 2. メッセージ送信

Python スクリプトで SQS にリクエストを送信：
```python
import json
import boto3
import uuid

client = boto3.client('sqs', region_name='ap-northeast-1')
request_id = 'test-9e68af4f'
message = {
    'id': request_id,
    'sql': "SELECT * FROM orders WHERE MK_DATE BETWEEN TO_DATE('2024-01-01','YYYY-MM-DD') AND TO_DATE('2024-12-31','YYYY-MM-DD')",
    'tns': 'ORCL_PROD',
    'app_id': 'app1'
}
response = client.send_message(
    QueueUrl='https://sqs.ap-northeast-1.amazonaws.com/590184009554/onprem-sql-request',
    MessageBody=json.dumps(message)
)
```

**結果**：  
- MessageId: `39d0e9c9-6185-426c-b27d-da47bf4b2796`
- MD5OfMessageBody: `b83a18289e035ccf659bbdb56c2bd06a`

### 3. 処理実行

ログで以下の処理を確認：
```
2026-02-22 00:27:27,696 [INFO] __main__ - [test-9e68af4f] メッセージ処理開始
2026-02-22 00:27:27,697 [INFO] mock_oracle - [MOCK] Oracle 接続、DSN=ORCL_PROD
2026-02-22 00:27:27,699 [INFO] mock_oracle - [MOCK] SELECT 実行…ダミーデータを返します
2026-02-22 00:27:27,701 [INFO] mock_oracle - [MOCK] ダミーデータ 3 行を返します…
2026-02-22 00:27:29,658 [INFO] __main__ - [test-9e68af4f] SELECT 結果をS3にアップロード: test-9e68af4f.json (3 行)
2026-02-22 00:27:29,852 [INFO] __main__ - [test-9e68af4f] SQS メッセージを削除しました。
```

### 4. 結果確認

S3 に保存されたファイル：
```bash
aws s3 ls s3://onprem-sql-result-590184009554-ap-northeast-1/
# → 2026-02-22 00:27:30        549 test-9e68af4f.json
```

---

## テスト結果

### ✅ 全テスト成功

| ステップ | 結果 | 詳細 |
|---------|------|------|
| **SQS メッセージ送信** | ✅ PASS | MessageId: 39d0e9c9-6185-426c-b27d-da47bf4b2796 |
| **オンプレエージェント受信** | ✅ PASS | ログ: "[test-9e68af4f] メッセージ処理開始" |
| **SQL バリデーション** | ✅ PASS | WHERE + MK_DATE BETWEEN で OK |
| **モック Oracle 実行** | ✅ PASS | ダミーデータ 3 行取得 (ORD-0001, ORD-0002, ORD-0003) |
| **S3 保存** | ✅ PASS | test-9e68af4f.json (549 bytes) |
| **メッセージ削除** | ✅ PASS | SQS からメッセージ削除完了 |

---

## S3 保存データ例

```json
{
  "value": [
    {
      "ORDER_ID": "ORD-0001",
      "CUSTOMER_NAME": "Mock顧客A",
      "AMOUNT": 12500,
      "MK_DATE": "2025-01-10",
      "STATUS": "COMPLETED",
      "_mock": true,
      "_executed_at": "2026-02-21T15:27:27.701361"
    },
    {
      "ORDER_ID": "ORD-0002",
      "CUSTOMER_NAME": "Mock顧客B",
      "AMOUNT": 87000,
      "MK_DATE": "2025-01-15",
      "STATUS": "PENDING",
      "_mock": true,
      "_executed_at": "2026-02-21T15:27:27.701361"
    },
    {
      "ORDER_ID": "ORD-0003",
      "CUSTOMER_NAME": "Mock顧客C",
      "AMOUNT": 3200,
      "MK_DATE": "2025-01-28",
      "STATUS": "COMPLETED",
      "_mock": true,
      "_executed_at": "2026-02-21T15:27:27.701361"
    }
  ],
  "Count": 3
}
```

---

## 工夫点・発見事項

### 1. JSON メッセージ形式

**問題**：PowerShell `ConvertTo-Json` コマンドで不正な JSON が生成される  
⟹ SQS メッセージ受信時に JSON デコードエラー

**改善**：Python `json.dumps()` で確実に正しい JSON を生成  
⟹ メッセージ処理成功

### 2. 環境変数管理

**改善**：`main.py` に `load_dotenv()` 追加  
```python
from dotenv import load_dotenv

def main() -> None:
    load_dotenv()  # .env ファイルから自動読み込み
    cfg = load_config()
```

メリット：
- 環境変数は自動で .env から読み込み
- ハードコード不要
- 本番・開発環境を簡単に切り替え可能

### 3. ログ可視化

ログレベル INFO で処理フロー全体が可視化：
- ✅ メッセージ受信
- ✅ Oracle 接続
- ✅ SQL 実行
- ✅ S3 アップロード
- ✅ メッセージ削除

---

## まとめ

### ✅ 検証完了内容

- **MOCK_MODE=true での全フロー検証完了** ✓
- **AWS ↔ オンプレミス間の非同期通信が正常に機能** ✓
- **システムアーキテクチャの信頼性確認** ✓

### 📝 次の検証項目

1. **本番モード (MOCK_MODE=false) テスト**  
   ⟹ 実 Oracle 接続環境が必要

2. **Lambda 統合テスト**  
   ⟹ Lambda 関数からも同様にメッセージを送信

3. **エラーハンドリング確認**  
   ⟹ 不正な SQL・接続エラー等の処理確認

4. **負荷テスト**  
   ⟹ 複数並行リクエストでの安定性確認

---

## テスト実行環境

- **OS**: Windows 11
- **Python**: 3.11.7
- **AWS Region**: ap-northeast-1
- **Mock Mode**: true
- **テスト日時**: 2026-02-22 00:27:30 UTC
