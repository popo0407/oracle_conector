"""
oracle_client.py
Oracle DB への ODBC 接続を管理するモジュール。

接続切断時の自動再接続と、接続プールの簡易ラッパーを提供する。
"""
from __future__ import annotations

import logging
from typing import Any

import pyodbc

from config import Config

logger = logging.getLogger(__name__)


class OracleClient:
    """
    Oracle DB（ODBC 経由）接続ラッパー。

    - `connect()` で接続を確立する。
    - `is_alive()` で疎通確認し、切断されていれば自動再接続する。
    - TNS 名を指定すると `connect()` で切り替え接続する。
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._conn: pyodbc.Connection | None = None
        self._current_tns: str | None = None

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    def connect(self, tns: str | None = None) -> None:
        """
        指定された TNS 名（または設定の ORACLE_DSN）で接続する。
        既に同じ DSN に接続済みであれば再接続しない。
        """
        target_tns = tns or self._cfg.oracle_dsn
        if self._conn is not None and self._current_tns == target_tns and self.is_alive():
            return  # 既存接続を再利用

        self._close_quietly()
        logger.info("Oracle に接続します: DSN=%s", target_tns)
        self._conn = pyodbc.connect(
            f"DSN={target_tns};UID={self._cfg.oracle_user};PWD={self._cfg.oracle_password}",
            autocommit=False,
            timeout=30,
        )
        self._current_tns = target_tns
        logger.info("Oracle 接続完了: DSN=%s", target_tns)

    def is_alive(self) -> bool:
        """疎通確認クエリで接続が有効かどうかを確認する。"""
        if self._conn is None:
            return False
        try:
            self._conn.cursor().execute("SELECT 1 FROM DUAL")
            return True
        except Exception:
            return False

    def execute_select(self, sql: str) -> list[dict[str, Any]]:
        """
        SELECT 文を実行し、結果を辞書のリストとして返す。

        Raises:
            ValueError: 接続が存在しない場合。
            pyodbc.Error: Oracle エラーが発生した場合。
        """
        self._ensure_connected()
        cursor = self._conn.cursor()  # type: ignore[union-attr]
        cursor.execute(sql)
        columns = [col[0] for col in cursor.description]
        rows = cursor.fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def execute_dml(self, sql: str) -> int:
        """
        INSERT / UPDATE 文を実行し、影響行数を返す。

        - 影響行数が 1 以外の場合はロールバックして ValueError を送出する。

        Raises:
            ValueError: 影響行数が 1 でない場合、または接続がない場合。
            pyodbc.Error: Oracle エラーが発生した場合。
        """
        self._ensure_connected()
        cursor = self._conn.cursor()  # type: ignore[union-attr]
        cursor.execute(sql)
        affected = cursor.rowcount
        if affected != 1:
            self._conn.rollback()  # type: ignore[union-attr]
            raise ValueError(
                f"INSERT/UPDATE は 1 行のみ許可されています（実際の影響行数: {affected}）"
            )
        self._conn.commit()  # type: ignore[union-attr]
        return affected

    def rollback(self) -> None:
        """トランザクションをロールバックする。接続がない場合は何もしない。"""
        if self._conn is not None:
            try:
                self._conn.rollback()
            except Exception as exc:
                logger.warning("rollback 失敗: %s", exc)

    def close(self) -> None:
        """接続を閉じる。"""
        self._close_quietly()

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._conn is None:
            raise ValueError("Oracle に接続されていません。connect() を先に呼び出してください。")

    def _close_quietly(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as exc:
                logger.debug("接続クローズ中にエラー: %s", exc)
            finally:
                self._conn = None
                self._current_tns = None
