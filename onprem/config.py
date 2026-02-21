"""
config.py
オンプレ Python エージェントの設定モジュール。
環境変数から値を読み込み、未設定の必須項目は起動時に ValueError を発生させる。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _require(key: str) -> str:
    """環境変数を必須で取得する。未設定なら ValueError を送出する。"""
    value = os.getenv(key)
    if not value:
        raise ValueError(f"環境変数 '{key}' が設定されていません。")
    return value


def _optional(key: str, default: str = "") -> str:
    return os.getenv(key, default)


@dataclass(frozen=True)
class Config:
    # AWS 設定
    aws_region: str
    role_arn: str
    request_queue_url: str
    response_queue_url: str
    result_bucket: str

    # Oracle 設定
    oracle_dsn: str
    oracle_user: str
    oracle_password: str

    # ネットワーク設定
    proxy_url: str

    # SNS アラート設定（任意）
    alert_topic_arn: str

    # ホワイトリスト
    allowed_app_ids: list[str] = field(default_factory=list)

    # STS セッション秒数
    session_duration_sec: int = 3600

    # セッション更新バッファ（期限 N 分前に更新）
    session_refresh_buffer_min: int = 5

    # SQS Long Polling 待機秒数
    sqs_wait_time_seconds: int = 10

    # クエリ結果の最大バイト数（デフォルト 8 MB）
    max_result_bytes: int = 8 * 1024 * 1024


def load_config() -> Config:
    """環境変数から Config を生成して返す。"""
    allowed_raw = _optional("ALLOWED_APP_IDS", "")
    allowed_app_ids = [a.strip() for a in allowed_raw.split(",") if a.strip()]

    return Config(
        aws_region=_optional("AWS_REGION", "ap-northeast-1"),
        role_arn=_require("ROLE_ARN"),
        request_queue_url=_require("REQUEST_QUEUE_URL"),
        response_queue_url=_require("RESPONSE_QUEUE_URL"),
        result_bucket=_require("RESULT_BUCKET"),
        oracle_dsn=_require("ORACLE_DSN"),
        oracle_user=_require("ORACLE_USER"),
        oracle_password=_require("ORACLE_PASSWORD"),
        proxy_url=_optional("PROXY_URL"),
        alert_topic_arn=_optional("ALERT_TOPIC_ARN"),
        allowed_app_ids=allowed_app_ids,
        session_duration_sec=int(_optional("SESSION_DURATION_SEC", "3600")),
        session_refresh_buffer_min=int(_optional("SESSION_REFRESH_BUFFER_MIN", "5")),
        sqs_wait_time_seconds=int(_optional("SQS_WAIT_TIME_SECONDS", "10")),
        max_result_bytes=int(_optional("MAX_RESULT_BYTES", str(8 * 1024 * 1024))),
    )
