"""
test_mock_oracle.py
mock_oracle モジュールのユニットテスト。

MockOracleClient が正しくダミーデータを返すかテストする。
"""
import pytest
from datetime import datetime
from mock_oracle import MockOracleClient


class TestMockOracleClient:
    """MockOracleClient のテスト。"""

    def setup_method(self):
        """各テスト前に MockOracleClient を生成。"""
        self.client = MockOracleClient()

    def test_connect(self):
        """connect() はエラーなく実行できる。"""
        self.client.connect()
        self.client.connect(tns="ORCL_PROD")  # 例外が発生しない

    def test_is_alive(self):
        """is_alive() は常に True を返す。"""
        assert self.client.is_alive() is True
        self.client.connect()
        assert self.client.is_alive() is True

    def test_execute_select_returns_rows(self):
        """execute_select() がダミーデータを返す。"""
        self.client.connect()
        rows = self.client.execute_select("SELECT * FROM orders WHERE mk_date BETWEEN '2025-01-01' AND '2025-01-31'")

        assert isinstance(rows, list)
        assert len(rows) == 3
        assert "ORDER_ID" in rows[0]
        assert "_mock" in rows[0]
        assert rows[0]["_mock"] is True

    def test_execute_select_data_structure(self):
        """execute_select() が正しいデータ構造を返す。"""
        self.client.connect()
        rows = self.client.execute_select("SELECT * FROM orders")

        assert len(rows) > 0
        for row in rows:
            assert isinstance(row, dict)
            # 必須フィールド
            assert "ORDER_ID" in row
            assert "CUSTOMER_NAME" in row
            assert "AMOUNT" in row
            assert "MK_DATE" in row
            # モークマーク
            assert "_mock" in row
            assert row["_mock"] is True
            assert "_executed_at" in row

    def test_execute_select_timestamp(self):
        """execute_select() が現在時刻を _executed_at に記録する。"""
        before = datetime.utcnow()
        self.client.connect()
        rows = self.client.execute_select("SELECT *")
        after = datetime.utcnow()

        assert len(rows) > 0
        executed_str = rows[0]["_executed_at"]
        executed = datetime.fromisoformat(executed_str)
        assert before <= executed <= after

    def test_execute_dml_returns_one(self):
        """execute_dml() が 1（影響行数）を返す。"""
        self.client.connect()
        affected = self.client.execute_dml("INSERT INTO orders VALUES(999, 'Test')")
        assert affected == 1

    def test_execute_dml_multiple_calls(self):
        """execute_dml() を複数回呼び出しても常に 1 を返す。"""
        self.client.connect()
        assert self.client.execute_dml("INSERT INTO orders VALUES(1)") == 1
        assert self.client.execute_dml("UPDATE orders SET name = 'Updated'") == 1
        assert self.client.execute_dml("INSERT INTO users VALUES(2)") == 1

    def test_rollback(self):
        """rollback() はエラーなく実行できる（何もしない）。"""
        self.client.connect()
        self.client.rollback()  # 例外が発生しない

    def test_close(self):
        """close() はエラーなく実行できる（何もしない）。"""
        self.client.connect()
        self.client.close()  # 例外が発生しない
        # 再度接続可能
        self.client.connect()

    def test_without_connect(self):
        """connect() を呼ばずに他の操作を実行してもエラーが発生しない。"""
        # モックのため connect() なしで実行可能
        rows = self.client.execute_select("SELECT *")
        assert len(rows) == 3

    def test_dummy_data_consistency(self):
        """複数回の execute_select でダミーデータが一貫している。"""
        self.client.connect()
        rows1 = self.client.execute_select("SELECT *")
        rows2 = self.client.execute_select("SELECT *")

        assert len(rows1) == len(rows2) == 3
        assert rows1[0]["ORDER_ID"] == rows2[0]["ORDER_ID"] == "ORD-0001"
        assert rows1[1]["CUSTOMER_NAME"] == rows2[1]["CUSTOMER_NAME"] == "Mock顧客B"
