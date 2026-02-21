"""
mock_oracle.py
Oracle DB のモック実装。

MOCK_MODE=true の場合、OracleClient の代わりにこのモジュールが使用される。
実際の Oracle には接続せず、ダミーデータを返す。

テスト・結合確認・オンプレ環境が整っていない段階でのエンドツーエンド動作確認を
目的としている。
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

logger = logging.getLogger(__name__)

# SELECT 結果のダミーデータ（テーブル名に関わらず同じデータを返す）
_DUMMY_ROWS: list[dict[str, Any]] = [
    {
        "ORDER_ID": "ORD-0001",
        "CUSTOMER_NAME": "Mock顧客A",
        "AMOUNT": 12500,
        "MK_DATE": "2025-01-10",
        "STATUS": "COMPLETED",
    },
    {
        "ORDER_ID": "ORD-0002",
        "CUSTOMER_NAME": "Mock顧客B",
        "AMOUNT": 87000,
        "MK_DATE": "2025-01-15",
        "STATUS": "PENDING",
    },
    {
        "ORDER_ID": "ORD-0003",
        "CUSTOMER_NAME": "Mock顧客C",
        "AMOUNT": 3200,
        "MK_DATE": "2025-01-28",
        "STATUS": "COMPLETED",
    },
]


class MockOracleClient:
    """
    Oracle DB のモッククライアント。

    OracleClient と同じインターフェースを持つため、
    main.py 側は型を意識せず切り替えられる。
    """

    def connect(self, tns: str | None = None) -> None:
        logger.info("[MOCK] Oracle 接続: DSN=%s（実際には接続しません）", tns or "DEFAULT")

    def is_alive(self) -> bool:
        return True

    def execute_select(self, sql: str) -> list[dict[str, Any]]:
        logger.info("[MOCK] SELECT 実行（ダミーデータを返します）: %s", sql[:120])
        # 実行日時・SQL を付加した識別用フィールドを追加して返す
        result = [
            {**row, "_mock": True, "_executed_at": datetime.utcnow().isoformat()}
            for row in _DUMMY_ROWS
        ]
        logger.info("[MOCK] ダミーデータ %d 件を返します。", len(result))
        return result

    def execute_dml(self, sql: str) -> int:
        logger.info("[MOCK] DML 実行（ダミー: affected_rows=1）: %s", sql[:120])
        return 1

    def rollback(self) -> None:
        logger.info("[MOCK] rollback（何もしません）")

    def close(self) -> None:
        logger.info("[MOCK] Oracle 接続クローズ（何もしません）")
