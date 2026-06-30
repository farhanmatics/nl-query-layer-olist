"""Shared helpers for the schema-aware function factories.

A ColumnRef carries a (table, column) tuple. The function SQL emitter
needs both pieces — the table to JOIN, the column to filter on. The
biggest footgun in the factory pattern is accidentally extracting
`.column` too early and then trying to use it as a ColumnRef. The
two helpers below make the typical SQL-build operations explicit and
fail loudly when a programmer makes a mistake.

These are intentionally small. They exist so the function bodies
read as "build a SQL string from the active schema" and the type
checker (and a code reviewer) can see at a glance which identifiers
are physical (table/column) and which are logical.
"""
from schemas.base import ColumnRef, SchemaConfig


def col_name(ref: ColumnRef) -> str:
    """Return the physical column name from a ColumnRef.

    Use this at the SQL-build site, every time. Never do
    `ref.column` inline in a string template — a reviewer can't
    tell whether `ref` is a ColumnRef or a string, and the bug
    (calling .column on a string) only surfaces at runtime.
    """
    return ref.column


def table_for(ref: ColumnRef, cfg: SchemaConfig) -> str:
    """Return the physical table name for the table a ColumnRef points to.

    The ColumnRef stores the *logical* table name (a key into
    `SchemaConfig.tables`); this resolves it to the physical name.
    """
    return cfg.get_table(ref.table)
