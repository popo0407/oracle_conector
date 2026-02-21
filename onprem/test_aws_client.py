"""
test_aws_client.py
aws_client モジュールの基本テスト。

実際の AWS 接続は行わず、Config の構造やポーリングルジックの確認のみ。
"""
import pytest
from datetime import datetime, timedelta, timezone
from config import Config
from aws_client import AwsClientManager


class TestAwsClientManagerInitialization:
    """AwsClientManager の初期化テスト。"""

    def test_initialization(self):
        """AwsClientManager が Config で初期化できる。"""
        cfg = Config(
            aws_region="ap-northeast-1",
            role_arn="arn:aws:iam::123456789:role/TestRole",
            request_queue_url="https://sqs.../req",
            response_queue_url="https://sqs.../res",
            result_bucket="test-bucket",
            oracle_dsn="TEST",
            oracle_user="user",
            oracle_password="pass",
            proxy_url="",
            alert_topic_arn="",
            allowed_app_ids=[],
        )
        manager = AwsClientManager(cfg)
        assert manager is not None

    def test_session_not_initialized_initially(self):
        """初期化直後は _session_data が None。"""
        cfg = Config(
            aws_region="ap-northeast-1",
            role_arn="arn:aws:iam::123456789:role/TestRole",
            request_queue_url="https://sqs.../req",
            response_queue_url="https://sqs.../res",
            result_bucket="test-bucket",
            oracle_dsn="TEST",
            oracle_user="user",
            oracle_password="pass",
            proxy_url="",
            alert_topic_arn="",
            allowed_app_ids=[],
        )
        manager = AwsClientManager(cfg)
        # _session_data は None（プライベート属性なので直接アクセス）
        assert manager._session_data is None


class TestAwsClientManagerConfig:
    """AwsClientManager が Config の設定を正しく保持しているか。"""

    def test_proxy_configuration(self):
        """プロキシ設定が _build_boto_config に渡される。"""
        cfg = Config(
            aws_region="ap-northeast-1",
            role_arn="arn:aws:iam::123456789:role/TestRole",
            request_queue_url="https://sqs.../req",
            response_queue_url="https://sqs.../res",
            result_bucket="test-bucket",
            oracle_dsn="TEST",
            oracle_user="user",
            oracle_password="pass",
            proxy_url="http://proxy.example.com:8080",
            alert_topic_arn="",
            allowed_app_ids=[],
        )
        manager = AwsClientManager(cfg)
        # _boto_config が生成される
        assert manager._boto_config is not None

    def test_session_duration_from_config(self):
        """Config の session_duration_sec が使用される。"""
        cfg = Config(
            aws_region="ap-northeast-1",
            role_arn="arn:aws:iam::123456789:role/TestRole",
            request_queue_url="https://sqs.../req",
            response_queue_url="https://sqs.../res",
            result_bucket="test-bucket",
            oracle_dsn="TEST",
            oracle_user="user",
            oracle_password="pass",
            proxy_url="",
            alert_topic_arn="",
            allowed_app_ids=[],
            session_duration_sec=7200,
        )
        manager = AwsClientManager(cfg)
        assert manager._cfg.session_duration_sec == 7200

    def test_refresh_buffer_from_config(self):
        """Config の session_refresh_buffer_min が使用される。"""
        cfg = Config(
            aws_region="ap-northeast-1",
            role_arn="arn:aws:iam::123456789:role/TestRole",
            request_queue_url="https://sqs.../req",
            response_queue_url="https://sqs.../res",
            result_bucket="test-bucket",
            oracle_dsn="TEST",
            oracle_user="user",
            oracle_password="pass",
            proxy_url="",
            alert_topic_arn="",
            allowed_app_ids=[],
            session_refresh_buffer_min=10,
        )
        manager = AwsClientManager(cfg)
        assert manager._cfg.session_refresh_buffer_min == 10


class TestAwsClientManagerSessionLogic:
    """セッション更新ロジックのテスト。"""

    def test_is_expiring_soon_no_session(self):
        """セッションがない場合、_is_expiring_soon() は True。"""
        cfg = Config(
            aws_region="ap-northeast-1",
            role_arn="arn:aws:iam::123456789:role/TestRole",
            request_queue_url="https://sqs.../req",
            response_queue_url="https://sqs.../res",
            result_bucket="test-bucket",
            oracle_dsn="TEST",
            oracle_user="user",
            oracle_password="pass",
            proxy_url="",
            alert_topic_arn="",
            allowed_app_ids=[],
        )
        manager = AwsClientManager(cfg)
        assert manager._is_expiring_soon() is True
