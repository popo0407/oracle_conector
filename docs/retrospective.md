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

---

## 2026-02-22 — ユニットテスト実装・全テスト成功

### アプローチ

Python モジュール（config / sql_validator / mock_oracle / aws_client）を単体テストし、実装の正確性を検証。
Lambda もテストサンプルを追加（フル統合は今後）。

### テスト実装完了

| テストモジュール        | テスト数 | 状況      | 内容                                                     |
| ----------------------- | -------- | --------- | -------------------------------------------------------- |
| `test_config.py`        | 6        | ✅ 全成功 | 環境変数読み込み・デフォルト値・型変換                   |
| `test_sql_validator.py` | 19       | ✅ 全成功 | SELECT WHERE/MK_DATE・DML サブクエリ・危険キーワード拒否 |
| `test_mock_oracle.py`   | 12       | ✅ 全成功 | ダミーデータ生成・タイムスタンプ・整合性                 |
| `test_aws_client.py`    | 6        | ✅ 全成功 | 初期化・Config 保持・セッション期限判定                  |
| **合計**                | **43**   | ✅ 全成功 | **実行時間 0.67s**                                       |

### テスト内容ハイライト

**SQL バリデーション (19 テスト)**

- ✅ SELECT に WHERE・MK_DATE・BETWEEN 必須
- ✅ INSERT/UPDATE のサブクエリ禁止
- ✅ DROP/DELETE/TRUNCATE/ALTER/EXECUTE 等を自動拒否
- ✅ 大文字小文字を区別しない
- ✅ 複数条件・インラインコメント対応

**モック Oracle (12 テスト)**

- ✅ connect() / is_alive() 呼び出し
- ✅ execute_select() でダミーデータ 3 行返却
- ✅ execute_dml() で affected_rows=1 返却
- ✅ \_mock, \_executed_at フィールド付加
- ✅ rollback() / close() エラーなし

**Config 管理 (6 テスト)**

- ✅ 必須フィールド未設定で ValueError
- ✅ MOCK_MODE・ALLOWED_APP_IDS パース
- ✅ 数値環境変数の型変換

### テスト実行コマンド

```bash
cd onprem
python -m pytest -v          # 詳細表示
python -m pytest -q          # サマリー表示
python -m pytest --cov       # カバレッジ測定（オプション）
```

### 改善点

- 単体テストにより、実装ロジックの正確性が確認できた。
- 危険キーワードの正規表現マッチング、環境変数パーサーの動作が検証された。
- テスト作成時にエッジケース（空 SQL・コメント・数値パース等）を洗い出した。

### 再発防止策

- 今後の機能追加（env 変数追加・SQL 制約追加等）があれば、対応テストを同時作成する。
- ユニットテストで検出できない統合レベルは、Lambda + 実オンプレ環境でのテストで対応。
