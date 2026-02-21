"""
main.py
オンプレミス Oracle SQL ブリッジ エージェント メインモジュール。

処理フロー:
  1. STS AssumeRole で一時クレデンシャルを取得する
  2. Oracle DB に接続する
  3. SQS リクエストキューを Long Polling でポーリングする
  4. メッセージを受け取り SQL を実行する（ODBC → Oracle）
  5. 結果を S3 または SQS レスポンスキューに送信する
  6. メッセージを削除する
  7. セッション期限が迫ったら自動更新する
  8. SIGTERM / SIGINT を受けたら Graceful shutdown する

起動方法:
  python main.py

環境変数:
  .env.example を参照のこと。
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from typing import Any

from botocore.exceptions import ClientError

from aws_client import AwsClientManager
from config import load_config
from mock_oracle import MockOracleClient
from oracle_client import OracleClient
from sql_validator import SqlValidationError, get_sql_type, validate

# ================================================================
# ログ設定
# ================================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler("onprem_sql_bridge.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ================================================================
# グローバル状態（Graceful shutdown 用フラグ）
# ================================================================
_running = True


def _shutdown_handler(signum: int, frame: object) -> None:
    global _running
    logger.info("シャットダウンシグナル（%s）を受信しました。処理中のメッセージ完了後に終了します。", signum)
    _running = False


signal.signal(signal.SIGTERM, _shutdown_handler)
signal.signal(signal.SIGINT, _shutdown_handler)


# ================================================================
# メッセージ処理
# ================================================================

def _validate_message_fields(body: dict[str, Any], allowed_app_ids: list[str]) -> None:
    """
    メッセージの必須フィールドとホワイトリストを検証する。

    Raises:
        ValueError: フィールドが不正な場合。
    """
    request_id = body.get("id")
    sql = body.get("sql")
    app_id = body.get("app_id")

    if not request_id:
        raise ValueError("メッセージに 'id' フィールドがありません。")
    if not sql:
        raise ValueError("メッセージに 'sql' フィールドがありません。")
    if not app_id:
        raise ValueError("メッセージに 'app_id' フィールドがありません。")
    if allowed_app_ids and app_id not in allowed_app_ids:
        raise ValueError(f"許可されていない app_id: '{app_id}'")


def _process_message(
    body: dict[str, Any],
    aws: AwsClientManager,
    oracle: OracleClient,
    max_result_bytes: int,
    result_bucket: str,
    response_queue_url: str,
) -> None:
    """
    SQS メッセージを処理する。

    - SQL を実行して結果を S3 またはレスポンスキューに送信する。
    - エラー時はエラー内容をレスポンスキューに送信する。
    """
    request_id: str = body["id"]
    sql: str = body["sql"]
    tns: str | None = body.get("tns")

    # SQL バリデーション
    validate(sql)  # SqlValidationError が発生したら呼び出し元でキャッチ

    # TNS 指定があれば接続切り替え
    oracle.connect(tns=tns)

    sql_type = get_sql_type(sql)

    if sql_type == "select":
        rows = oracle.execute_select(sql)
        result_json = json.dumps(rows, ensure_ascii=False, default=str)

        # 結果サイズチェック
        result_bytes = result_json.encode("utf-8")
        if len(result_bytes) > max_result_bytes:
            raise ValueError(
                f"SELECT 結果が上限 ({max_result_bytes // (1024 * 1024)} MB) を超えています。"
                f"（実際のサイズ: {len(result_bytes) // (1024 * 1024)} MB）"
            )

        s3_key = f"{request_id}.json"
        aws.s3.put_object(  # type: ignore[union-attr]
            Bucket=result_bucket,
            Key=s3_key,
            Body=result_bytes,
            ContentType="application/json",
        )
        logger.info("[%s] SELECT 結果を S3 にアップロード: %s (%d 件)", request_id, s3_key, len(rows))
        payload: dict[str, Any] = {"id": request_id, "s3_key": s3_key}

    else:
        affected = oracle.execute_dml(sql)
        logger.info("[%s] DML 実行完了: affected_rows=%d", request_id, affected)
        payload = {"id": request_id, "affected_rows": affected}

    aws.sqs.send_message(  # type: ignore[union-attr]
        QueueUrl=response_queue_url,
        MessageBody=json.dumps(payload),
    )


def _handle_message(
    msg: dict[str, Any],
    aws: AwsClientManager,
    oracle: OracleClient,
    cfg: Any,
) -> None:
    """1 件の SQS メッセージを受け取って処理し、完了後に削除する。"""
    receipt_handle: str = msg["ReceiptHandle"]
    body: dict[str, Any] = json.loads(msg["Body"])
    request_id: str = body.get("id", "UNKNOWN")

    logger.info("[%s] メッセージ処理開始", request_id)

    try:
        _validate_message_fields(body, cfg.allowed_app_ids)
        _process_message(
            body=body,
            aws=aws,
            oracle=oracle,
            max_result_bytes=cfg.max_result_bytes,
            result_bucket=cfg.result_bucket,
            response_queue_url=cfg.response_queue_url,
        )

    except (ValueError, SqlValidationError) as exc:
        # バリデーションエラー: SQL / フィールド不正
        logger.warning("[%s] バリデーションエラー: %s", request_id, exc)
        oracle.rollback()
        _send_error_response(aws, cfg.response_queue_url, request_id, str(exc))

    except Exception as exc:
        # SQL 実行エラー、S3 書き込みエラーなど
        logger.error("[%s] 処理エラー: %s", request_id, exc, exc_info=True)
        oracle.rollback()
        _send_error_response(aws, cfg.response_queue_url, request_id, str(exc))

    finally:
        # 正常・エラーにかかわらずメッセージを削除（DLQ は maxReceiveCount で制御）
        try:
            aws.sqs.delete_message(  # type: ignore[union-attr]
                QueueUrl=cfg.request_queue_url,
                ReceiptHandle=receipt_handle,
            )
            logger.info("[%s] SQS メッセージを削除しました。", request_id)
        except ClientError as del_exc:
            logger.error("[%s] SQS メッセージ削除失敗: %s", request_id, del_exc)


def _send_error_response(
    aws: AwsClientManager,
    response_queue_url: str,
    request_id: str,
    error_message: str,
) -> None:
    """エラーレスポンスをレスポンスキューに送信する。"""
    try:
        aws.sqs.send_message(  # type: ignore[union-attr]
            QueueUrl=response_queue_url,
            MessageBody=json.dumps({"id": request_id, "error": error_message}),
        )
    except Exception as exc:
        logger.error("[%s] エラーレスポンス送信失敗: %s", request_id, exc)


# ================================================================
# メインループ
# ================================================================

def main() -> None:
    logger.info("OnPrem SQL ブリッジ エージェントを起動します。")

    # 設定読み込み
    cfg = load_config()
    logger.info(
        "設定ロード完了: region=%s, request_queue=%s, mock_mode=%s",
        cfg.aws_region,
        cfg.request_queue_url,
        cfg.mock_mode,
    )

    # AWS クライアント初期化（AssumeRole）
    aws = AwsClientManager(cfg)
    aws.refresh_if_needed()

    # Oracle 接続（モックモードでは MockOracleClient を使用）
    if cfg.mock_mode:
        logger.warning("=" * 60)
        logger.warning("【MOCK MODE 有効】Oracle には接続しません。")
        logger.warning("ダミーデータが S3 に保存されます。")
        logger.warning("本番投入前に MOCK_MODE=false に変更してください。")
        logger.warning("=" * 60)
        oracle: OracleClient | MockOracleClient = MockOracleClient()
    else:
        oracle = OracleClient(cfg)

    oracle.connect()

    logger.info("起動完了。SQS ポーリングを開始します...")

    backoff_sec = 1

    while _running:
        try:
            # セッション期限チェック・更新
            aws.refresh_if_needed()

            # Oracle 疎通確認
            if not oracle.is_alive():
                logger.warning("Oracle 接続が切断されています。再接続します...")
                oracle.connect()

            # SQS Long Polling
            response = aws.sqs.receive_message(  # type: ignore[union-attr]
                QueueUrl=cfg.request_queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=cfg.sqs_wait_time_seconds,
            )
            messages = response.get("Messages", [])

            if not messages:
                backoff_sec = 1  # 正常ポーリングではバックオフをリセット
                continue

            for msg in messages:
                _handle_message(msg=msg, aws=aws, oracle=oracle, cfg=cfg)

            backoff_sec = 1  # 成功したらリセット

        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "UNKNOWN")
            logger.error("AWS エラー (%s): %s", error_code, exc)
            aws.publish_alert(
                subject=f"[OnPremSqlBridge] AWS エラー: {error_code}",
                message=str(exc),
            )
            time.sleep(min(backoff_sec, 60))
            backoff_sec = min(backoff_sec * 2, 60)

        except Exception as exc:
            logger.error("予期しないエラー: %s", exc, exc_info=True)
            aws.publish_alert(
                subject="[OnPremSqlBridge] 予期しないエラー",
                message=str(exc),
            )
            time.sleep(min(backoff_sec, 60))
            backoff_sec = min(backoff_sec * 2, 60)

    # Graceful shutdown
    logger.info("シャットダウン処理中...")
    oracle.close()
    logger.info("エージェントを正常終了しました。")


if __name__ == "__main__":
    main()
