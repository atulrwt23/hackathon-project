from __future__ import annotations

import sqlglot
from sqlglot import exp


class SQLValidationError(ValueError):
    pass


_ALLOWED_ROOTS: tuple[type[exp.Expression], ...] = (exp.Select, exp.Union, exp.With, exp.Subquery)

_FORBIDDEN: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
)


def validate_and_cap(sql: str, *, max_rows: int) -> str:
    """Parse SQL with sqlglot, enforce read-only, inject/cap LIMIT, return normalized SQL.

    Raises SQLValidationError on any rejection.
    """
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        raise SQLValidationError("empty SQL")

    try:
        statements = sqlglot.parse(sql, dialect="postgres")
    except sqlglot.errors.ParseError as e:
        raise SQLValidationError(f"unparseable SQL: {e}") from e

    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise SQLValidationError(
            f"exactly one statement required, got {len(statements)}"
        )

    tree = statements[0]

    if not isinstance(tree, _ALLOWED_ROOTS):
        raise SQLValidationError(
            f"only SELECT/WITH/UNION allowed at top level, got {type(tree).__name__}"
        )

    for node in tree.walk():
        if isinstance(node, _FORBIDDEN):
            raise SQLValidationError(f"forbidden statement type: {type(node).__name__}")

    capped = _apply_limit(tree, max_rows)
    return capped.sql(dialect="postgres")


def _apply_limit(tree: exp.Expression, max_rows: int) -> exp.Expression:
    """Wrap the tree so an outer LIMIT max_rows is always applied.

    Wrapping (rather than mutating any inner LIMIT) guarantees the cap even if
    the inner query uses larger pagination internally.
    """
    return exp.select("*").from_(tree.subquery("nl2sql_capped")).limit(max_rows)
