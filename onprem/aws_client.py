"""
aws_client.py
AWS サービス（STS / SQS / S3 / SNS）のクライアント管理モジュール。

セッション自動更新と boto3 クライアントの生成・再生成を一元管理する。
呼び出し側は AwsClientManager 経由でクライアントを取得することで、
セッション期限切れを気にせず実装できる。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config as BotocoreConfig

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sns import SNSClient

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class _Session:
    sqs: object
    s3: object
    sns: object
    expiration: datetime


def _build_boto_config(proxy_url: str) -> BotocoreConfig:
    """プロキシとリトライ設定を含む botocore Config を生成する。"""
    proxies = {"https": proxy_url} if proxy_url else {}
    return BotocoreConfig(
        retries={"max_attempts": 3, "mode": "adaptive"},
        connect_timeout=5,
        read_timeout=30,
        proxies=proxies,
    )


class AwsClientManager:
    """
    STS AssumeRole によるセッション管理と各 AWS クライアントを提供するクラス。

    - セッション期限の `session_refresh_buffer_min` 分前に自動更新する。
    - プロキシが設定されている場合は全クライアントに適用する。
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._boto_config = _build_boto_config(cfg.proxy_url)
        self._session_data: _Session | None = None

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    def refresh_if_needed(self) -> None:
        """必要に応じてセッションを更新する。初回は必ず更新する。"""
        if self._session_data is None or self._is_expiring_soon():
            self._assume_role()

    @property
    def sqs(self) -> object:
        self.refresh_if_needed()
        return self._session_data.sqs  # type: ignore[union-attr]

    @property
    def s3(self) -> object:
        self.refresh_if_needed()
        return self._session_data.s3  # type: ignore[union-attr]

    @property
    def sns(self) -> object:
        self.refresh_if_needed()
        return self._session_data.sns  # type: ignore[union-attr]

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _is_expiring_soon(self) -> bool:
        if self._session_data is None:
            return True
        buffer = timedelta(minutes=self._cfg.session_refresh_buffer_min)
        return datetime.now(tz=timezone.utc) > self._session_data.expiration - buffer

    def _assume_role(self) -> None:
        logger.info("STS AssumeRole を実行します: %s", self._cfg.role_arn)
        sts = boto3.client(
            "sts",
            region_name=self._cfg.aws_region,
            config=self._boto_config,
        )
        resp = sts.assume_role(
            RoleArn=self._cfg.role_arn,
            RoleSessionName="OnPremSession",
            DurationSeconds=self._cfg.session_duration_sec,
        )
        creds = resp["Credentials"]
        expiration: datetime = creds["Expiration"]  # timezone-aware datetime

        session = boto3.Session(
            aws_access_key_id=creds["AccessKeyId"],
            aws_secret_access_key=creds["SecretAccessKey"],
            aws_session_token=creds["SessionToken"],
            region_name=self._cfg.aws_region,
        )

        self._session_data = _Session(
            sqs=session.client("sqs", config=self._boto_config),
            s3=session.client("s3", config=self._boto_config),
            sns=session.client("sns", config=self._boto_config),
            expiration=expiration,
        )
        logger.info("STS セッション取得完了。期限: %s (UTC)", expiration.isoformat())

    def publish_alert(self, subject: str, message: str) -> None:
        """SNS にアラートを送信する。ALERT_TOPIC_ARN が未設定の場合はスキップ。"""
        if not self._cfg.alert_topic_arn:
            logger.debug("ALERT_TOPIC_ARN が未設定のため SNS 通知をスキップします。")
            return
        try:
            self.sns.publish(  # type: ignore[union-attr]
                TopicArn=self._cfg.alert_topic_arn,
                Subject=subject[:100],
                Message=message[:8192],
            )
            logger.info("SNS アラートを送信しました: %s", subject)
        except Exception as exc:
            logger.error("SNS アラート送信失敗: %s", exc)
