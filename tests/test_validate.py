from __future__ import annotations

import pytest

from nl2sql.validate import SQLValidationError, validate_and_cap


def test_select_is_allowed_and_capped():
    out = validate_and_cap("SELECT id, name FROM users", max_rows=100)
    assert "LIMIT 100" in out.upper()
    assert "FROM users" in out.lower() or "from users" in out.lower()


def test_with_cte_is_allowed():
    sql = "WITH active AS (SELECT id FROM users WHERE flg = 'A') SELECT count(*) FROM active"
    out = validate_and_cap(sql, max_rows=50)
    assert "LIMIT 50" in out.upper()


def test_union_is_allowed():
    sql = "SELECT id FROM a UNION SELECT id FROM b"
    out = validate_and_cap(sql, max_rows=10)
    assert "LIMIT 10" in out.upper()


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (id) VALUES (1)",
        "UPDATE users SET name = 'x' WHERE id = 1",
        "DELETE FROM users WHERE id = 1",
        "DROP TABLE users",
        "CREATE TABLE t (id int)",
        "ALTER TABLE users ADD COLUMN x int",
        "TRUNCATE TABLE users",
        "GRANT SELECT ON users TO public",
    ],
)
def test_mutations_are_rejected(sql: str):
    with pytest.raises(SQLValidationError):
        validate_and_cap(sql, max_rows=100)


def test_multiple_statements_rejected():
    with pytest.raises(SQLValidationError):
        validate_and_cap("SELECT 1; SELECT 2", max_rows=10)


def test_unparseable_rejected():
    with pytest.raises(SQLValidationError):
        validate_and_cap("SELECT FROM WHERE", max_rows=10)


def test_empty_rejected():
    with pytest.raises(SQLValidationError):
        validate_and_cap("   ", max_rows=10)


def test_inner_limit_is_overridden_by_outer_cap():
    # The wrap-with-LIMIT strategy means even if the model emits LIMIT 99999, the cap still wins.
    out = validate_and_cap("SELECT * FROM users LIMIT 99999", max_rows=25)
    assert "LIMIT 25" in out.upper()


def test_dml_inside_cte_rejected():
    with pytest.raises(SQLValidationError):
        validate_and_cap(
            "WITH d AS (DELETE FROM users RETURNING id) SELECT * FROM d",
            max_rows=10,
        )
