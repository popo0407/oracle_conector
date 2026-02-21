"""
sql_validator.py
SQL 文のバリデーションモジュール。

設計書の要件に基づき、以下を検証する:
  - SELECT  : WHERE 句と MK_DATE 範囲指定が必須
  - INSERT / UPDATE: 単一レコード操作であること（事前チェック）
  - それ以外の SQL 種別（DROP / DELETE など）は拒否
"""
from __future__ import annotations

import re


# 許可する SQL の先頭キーワード
_ALLOWED_PREFIXES = ("select", "insert", "update")

# MK_DATE 使用チェック用正規表現
_RE_MK_DATE = re.compile(r"\bmk_date\b", re.IGNORECASE)
_RE_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)
_RE_BETWEEN = re.compile(r"\bbetween\b", re.IGNORECASE)

# 危険なキーワードのブラックリスト（前後が単語境界）
_DANGEROUS_KEYWORDS = re.compile(
    r"\b(drop|truncate|alter|create|grant|revoke|exec|execute|xp_|sp_|"
    r"information_schema|sys\.|dual\.)\b",
    re.IGNORECASE,
)


class SqlValidationError(ValueError):
    """SQL バリデーションエラー。"""


def validate(sql: str) -> None:
    """
    SQL 文を検証する。問題がある場合は SqlValidationError を送出する。

    Args:
        sql: 実行予定の SQL 文字列。

    Raises:
        SqlValidationError: SQL が要件を満たさない場合。
    """
    stripped = sql.strip()
    if not stripped:
        raise SqlValidationError("SQL が空です。")

    # 危険キーワードチェック
    if _DANGEROUS_KEYWORDS.search(stripped):
        raise SqlValidationError("許可されていないキーワードが含まれています。")

    lower = stripped.lower()
    prefix = _get_prefix(lower)

    if prefix == "select":
        _validate_select(stripped)
    elif prefix in ("insert", "update"):
        # INSERT/UPDATE の事前チェックは最低限（行数は実行後に確認）
        _validate_dml(stripped)
    else:
        raise SqlValidationError(
            f"サポートされていない SQL 種別です: '{prefix}'. "
            "SELECT / INSERT / UPDATE のみ許可されています。"
        )


def get_sql_type(sql: str) -> str:
    """SQL 種別文字列（'select' / 'dml'）を返す。"""
    lower = sql.strip().lower()
    if lower.startswith("select"):
        return "select"
    return "dml"


# ------------------------------------------------------------------
# 内部実装
# ------------------------------------------------------------------

def _get_prefix(lower_sql: str) -> str:
    for prefix in _ALLOWED_PREFIXES:
        if lower_sql.startswith(prefix):
            return prefix
    # 先頭が許可プレフィックスでない場合は最初の単語を返す
    return lower_sql.split()[0] if lower_sql.split() else ""


def _validate_select(sql: str) -> None:
    if not _RE_WHERE.search(sql):
        raise SqlValidationError(
            "SELECT 文には WHERE 句が必要です。"
        )
    if not _RE_MK_DATE.search(sql):
        raise SqlValidationError(
            "SELECT 文には WHERE 句内に MK_DATE 列の指定が必要です。"
        )
    if not _RE_BETWEEN.search(sql):
        raise SqlValidationError(
            "SELECT 文の MK_DATE には BETWEEN による範囲指定が必要です。"
        )


def _validate_dml(sql: str) -> None:
    # サブクエリを含む UPDATE/INSERT は禁止（単一レコード操作の担保）
    lower = sql.lower()
    if "select" in lower:
        raise SqlValidationError(
            "INSERT / UPDATE 内にサブクエリ（SELECT）を含めることはできません。"
        )
