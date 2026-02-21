"""
test_config.py
config モジュールのユニットテスト。

環境変数の読み込みと Config オブジェクト生成をテストする。
"""
import os
import pytest
from config import Config, load_config


class TestLoadConfig:
    """環境変数からの Config 生成テスト。"""

    def setup_method(self):
        """各テスト前に環境変数をクリア。"""
        for key in [
            "AWS_REGION",
            "ROLE_ARN",
            "REQUEST_QUEUE_URL",
            "RESPONSE_QUEUE_URL",
            "RESULT_BUCKET",
            "ORACLE_DSN",
            "ORACLE_USER",
            "ORACLE_PASSWORD",
            "PROXY_URL",
            "ALLOWED_APP_IDS",
            "MOCK_MODE",
        ]:
            os.environ.pop(key, None)

    def test_required_fields_missing(self):
        """必須フィールド未設定で ValueError が発生する。"""
        with pytest.raises(ValueError, match="環境変数 'ROLE_ARN' が設定されていません"):
            load_config()

    def test_minimal_config(self):
        """最小限の環境変数で Config が生成できる。"""
        os.environ["ROLE_ARN"] = "arn:aws:iam::123456789:role/MyRole"
        os.environ["REQUEST_QUEUE_URL"] = "https://sqs.ap-northeast-1.amazonaws.com/123/req"
        os.environ["RESPONSE_QUEUE_URL"] = "https://sqs.ap-northeast-1.amazonaws.com/123/res"
        os.environ["RESULT_BUCKET"] = "my-bucket"
        os.environ["ORACLE_DSN"] = "ORCL"
        os.environ["ORACLE_USER"] = "dbuser"
        os.environ["ORACLE_PASSWORD"] = "dbpass"

        cfg = load_config()

        assert cfg.role_arn == "arn:aws:iam::123456789:role/MyRole"
        assert cfg.oracle_dsn == "ORCL"
        assert cfg.mock_mode is False  # デフォルト

    def test_mock_mode_enabled(self):
        """MOCK_MODE=true で mock_mode フラグが True になる。"""
        os.environ["ROLE_ARN"] = "arn:test"
        os.environ["REQUEST_QUEUE_URL"] = "https://sqs.../req"
        os.environ["RESPONSE_QUEUE_URL"] = "https://sqs.../res"
        os.environ["RESULT_BUCKET"] = "mybucket"
        os.environ["ORACLE_DSN"] = "DSN"
        os.environ["ORACLE_USER"] = "user"
        os.environ["ORACLE_PASSWORD"] = "pass"
        os.environ["MOCK_MODE"] = "true"

        cfg = load_config()
        assert cfg.mock_mode is True

    def test_allowed_app_ids_parsing(self):
        """ALLOWED_APP_IDS のカンマ区切りパーステスト。"""
        os.environ["ROLE_ARN"] = "arn:test"
        os.environ["REQUEST_QUEUE_URL"] = "https://sqs.../req"
        os.environ["RESPONSE_QUEUE_URL"] = "https://sqs.../res"
        os.environ["RESULT_BUCKET"] = "mybucket"
        os.environ["ORACLE_DSN"] = "DSN"
        os.environ["ORACLE_USER"] = "user"
        os.environ["ORACLE_PASSWORD"] = "pass"
        os.environ["ALLOWED_APP_IDS"] = "app1,app2,app3"

        cfg = load_config()
        assert cfg.allowed_app_ids == ["app1", "app2", "app3"]

    def test_allowed_app_ids_empty_string(self):
        """ALLOWED_APP_IDS が未設定またはから文字列の場合は空リスト。"""
        os.environ["ROLE_ARN"] = "arn:test"
        os.environ["REQUEST_QUEUE_URL"] = "https://sqs.../req"
        os.environ["RESPONSE_QUEUE_URL"] = "https://sqs.../res"
        os.environ["RESULT_BUCKET"] = "mybucket"
        os.environ["ORACLE_DSN"] = "DSN"
        os.environ["ORACLE_USER"] = "user"
        os.environ["ORACLE_PASSWORD"] = "pass"

        cfg = load_config()
        assert cfg.allowed_app_ids == []

    def test_numeric_env_vars(self):
        """数値の環境変数のパーステスト。"""
        os.environ["ROLE_ARN"] = "arn:test"
        os.environ["REQUEST_QUEUE_URL"] = "https://sqs.../req"
        os.environ["RESPONSE_QUEUE_URL"] = "https://sqs.../res"
        os.environ["RESULT_BUCKET"] = "mybucket"
        os.environ["ORACLE_DSN"] = "DSN"
        os.environ["ORACLE_USER"] = "user"
        os.environ["ORACLE_PASSWORD"] = "pass"
        os.environ["SESSION_DURATION_SEC"] = "7200"
        os.environ["MAX_RESULT_BYTES"] = "1048576"

        cfg = load_config()
        assert cfg.session_duration_sec == 7200
        assert cfg.max_result_bytes == 1048576
