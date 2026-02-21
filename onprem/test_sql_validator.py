"""
test_sql_validator.py
sql_validator モジュールのユニットテスト。

SQL の検証ロジックをテストする。
"""
import pytest
from sql_validator import SqlValidationError, validate, get_sql_type


class TestSelectValidation:
    """SELECT 文の検証テスト。"""

    def test_select_with_mk_date_between(self):
        """MK_DATE BETWEEN を含む SELECT は許可される。"""
        sql = "SELECT * FROM orders WHERE mk_date BETWEEN '2025-01-01' AND '2025-01-31'"
        validate(sql)  # 例外が発生しないことを確認

    def test_select_without_where(self):
        """SELECT に WHERE がない場合は拒否される。"""
        with pytest.raises(SqlValidationError, match="WHERE 句が必要"):
            validate("SELECT * FROM orders")

    def test_select_without_mk_date(self):
        """SELECT に MK_DATE がない場合は拒否される。"""
        with pytest.raises(SqlValidationError, match="MK_DATE"):
            validate("SELECT * FROM orders WHERE id = 123")

    def test_select_without_between(self):
        """MK_DATE に BETWEEN がない場合は拒否される。"""
        with pytest.raises(SqlValidationError, match="BETWEEN"):
            validate("SELECT * FROM orders WHERE mk_date = '2025-01-01'")

    def test_select_case_insensitive(self):
        """SQL キーワードは大文字小文字を区別しない。"""
        sql = "select * from orders where mk_date between '2025-01-01' and '2025-01-31'"
        validate(sql)  # 成功

    def test_select_with_multiple_conditions(self):
        """MK_DATE BETWEEN 以外の条件も含む SELECT は許可される。"""
        sql = """
        SELECT order_id, amount FROM orders 
        WHERE status = 'COMPLETED' 
          AND mk_date BETWEEN '2025-01-01' AND '2025-01-31'
        """
        validate(sql)  # 成功


class TestDMLValidation:
    """INSERT / UPDATE 文の検証テスト。"""

    def test_insert_without_subquery(self):
        """INSERT にサブクエリがない場合は許可される。"""
        sql = "INSERT INTO orders(id, name) VALUES(123, 'Order-001')"
        validate(sql)  # 成功

    def test_insert_with_subquery(self):
        """INSERT にサブクエリ（SELECT）を含む場合は拒否される。"""
        with pytest.raises(SqlValidationError, match="サブクエリ"):
            validate("INSERT INTO orders SELECT * FROM backup_orders")

    def test_update_without_subquery(self):
        """UPDATE にサブクエリがない場合は許可される。"""
        sql = "UPDATE orders SET status = 'SHIPPED' WHERE id = 123"
        validate(sql)  # 成功

    def test_update_with_subquery(self):
        """UPDATE にサブクエリを含む場合は拒否される。"""
        with pytest.raises(SqlValidationError, match="サブクエリ"):
            validate("UPDATE orders SET count = (SELECT COUNT(*) FROM items) WHERE id = 123")


class TestDangerousKeywords:
    """危険キーワードの検出テスト。"""

    def test_drop_statement(self):
        """DROP コマンドは拒否される。"""
        with pytest.raises(SqlValidationError, match="許可されていないキーワード"):
            validate("DROP TABLE orders")

    def test_delete_statement(self):
        """DELETE コマンドは拒否される。"""
        with pytest.raises(SqlValidationError):
            validate("DELETE FROM orders WHERE id = 123")

    def test_truncate_statement(self):
        """TRUNCATE コマンドは拒否される。"""
        with pytest.raises(SqlValidationError, match="許可されていないキーワード"):
            validate("TRUNCATE TABLE orders")

    def test_alter_statement(self):
        """ALTER コマンドは拒否される。"""
        with pytest.raises(SqlValidationError, match="許可されていないキーワード"):
            validate("ALTER TABLE orders ADD COLUMN new_col INT")

    def test_execute_statement(self):
        """EXECUTE コマンドは拒否される。"""
        with pytest.raises(SqlValidationError, match="許可されていないキーワード"):
            validate("EXECUTE sp_executesql")


class TestGetSqlType:
    """SQL 種別判定テスト。"""

    def test_select_type(self):
        assert get_sql_type("SELECT * FROM orders") == "select"
        assert get_sql_type("select id FROM users") == "select"

    def test_dml_type(self):
        assert get_sql_type("INSERT INTO orders VALUES(1)") == "dml"
        assert get_sql_type("UPDATE orders SET id = 1") == "dml"
        assert get_sql_type("insert into users(name) values('test')") == "dml"


class TestEdgeCases:
    """エッジケースのテスト。"""

    def test_empty_sql(self):
        """空の SQL は拒否される。"""
        with pytest.raises(SqlValidationError, match="SQL が空"):
            validate("")

    def test_whitespace_only_sql(self):
        """スペースのみの SQL は拒否される。"""
        with pytest.raises(SqlValidationError, match="SQL が空"):
            validate("   ")

    def test_sql_with_inline_comments(self):
        """SELECT にインラインコメント（`/* */` 形式）を含めても許可される。"""
        sql = "SELECT /* comment */ * FROM orders WHERE mk_date BETWEEN '2025-01-01' AND '2025-01-31'"
        validate(sql)  # 成功
