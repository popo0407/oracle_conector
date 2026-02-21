---
# docs/retrospective.md
---

# 振り返り記録

## 2026-02-21 — AWS CDK ＋ オンプレ Python エージェント実装

### 問題の概要

ドキュメント（設計書・参考実装・CDK テンプレート）を元に、  
AWS 側（CDK TypeScript）とオンプレミス側（Python）をゼロから実装した。

---

### 実装内容

#### AWS 側 (`aws/`)

| ファイル                          | 内容                                                                |
| --------------------------------- | ------------------------------------------------------------------- |
| `bin/app.ts`                      | CDK エントリーポイント。環境変数からアカウント/リージョンを注入。   |
| `lib/on-prem-sql-bridge-stack.ts` | KMS/S3/SQS/DLQ/SNS/IAM/Lambda/CloudWatch を定義するメインスタック。 |
| `lambda/request-sender/index.ts`  | SQS 送信 + レスポンスポーリング + S3 取得を行う Lambda 関数。       |

設計書に沿い以下を追加実装：

- `kms:ViaService` を `s3` と `sqs` 両方に拡張（参考コードは S3 のみだった）
- `DenyNonSsl` ステートメントで HTTPS 強制
- CloudWatch アラーム（DLQ 増加 / キュー滞留）
- `CfnOutput` で CDK デプロイ後の接続情報を出力
- CDK コンテキスト変数（`allowedOnPremIp`）で IP を外部注入可能に

#### オンプレ側 (`onprem/`)

| ファイル           | 内容                                                                                      |
| ------------------ | ----------------------------------------------------------------------------------------- |
| `config.py`        | 環境変数から `Config` dataclass を生成。必須項目未設定で即 ValueError。                   |
| `aws_client.py`    | `AwsClientManager` クラスでセッション自動更新・プロキシ設定を一元管理。                   |
| `oracle_client.py` | `OracleClient` クラスで ODBC 接続・再接続・execute_select/execute_dml を担当。            |
| `sql_validator.py` | SELECT: WHERE + MK_DATE BETWEEN 必須。DML: サブクエリ禁止。危険キーワードブラックリスト。 |
| `main.py`          | シグナルハンドラ、SQS ポーリングループ、エラーハンドリング、SNS 通知、Graceful shutdown。 |

---

### 改善点・工夫点

1. **単一責任の分離**  
   参考実装は `main.py` 1 ファイルに全処理が混在していたため、  
   `config`, `aws_client`, `oracle_client`, `sql_validator` に分割。

2. **セッション管理の一元化**  
   `AwsClientManager` が期限確認・再取得・クライアント再生成をカプセル化。  
   メインループからは `aws.sqs` を呼ぶだけでよい。

3. **Oracle 接続切断の自動回復**  
   `is_alive()` + `connect()` でポーリングループ毎に疎通確認し自動再接続。

4. **エクスポネンシャルバックオフ**  
   AWS エラー・予期しないエラー時に最大 60 秒まで待機間隔を倍増。

5. **結果サイズ上限チェック**  
   `MAX_RESULT_BYTES` 環境変数で上限を設定し、超過時はエラーレスポンスを返す（設計書要件）。

---

### 再発防止策

- 参考実装コードをそのままコピーせず、設計書の要件を重ねてレビューしてから実装する。
- KMS の `kms:ViaService` は対象 AWS サービスが増えると漏れが生じるため、  
  CDK スタック変更時は条件を確認する。
- `ORACLE_PASSWORD` 等の秘匿情報は将来的に AWS Secrets Manager への移行を検討すること（Issue 登録済み）。

---

### 今後の課題（Issue 候補）

- 🔧 Oracle パスワードを環境変数から AWS Secrets Manager に移行
- ✨ Lambda からのレスポンス受信を SQS ポーリングではなく EventBridge Pipes に変更検討
- 🚀 オンプレ側の Python バージョン管理とパッケージ署名検証（pip hash）の導入
