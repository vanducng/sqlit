"""Unit tests for the pure node-name resolver used by the tree ty leader menu."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from sqlit.domains.explorer.app.node_name_resolver import NodeNames, resolve_node_names
from sqlit.domains.explorer.domain.tree_nodes import (
    ColumnNode,
    ConnectionFolderNode,
    ConnectionNode,
    DatabaseNode,
    FolderNode,
    IndexNode,
    LoadingNode,
    ProcedureNode,
    SchemaNode,
    SequenceNode,
    TableNode,
    TriggerNode,
    ViewNode,
)


class IdentityDialect:
    """Dialect whose quote_identifier is the identity function."""

    def quote_identifier(self, name: str) -> str:
        return name

    def build_select_query(
        self, table: str, limit: int, database: str | None = None, schema: str | None = None
    ) -> str:
        parts = [p for p in (database, schema, table) if p]
        return f"SELECT * FROM {'.'.join(parts)} LIMIT {limit}"

    def format_table_name(self, schema: str | None, table: str) -> str:
        return f"{schema}.{table}" if schema else table


class DoubleQuoteDialect:
    """Dialect that wraps identifiers in double quotes."""

    def quote_identifier(self, name: str) -> str:
        return f'"{name}"'

    def build_select_query(
        self, table: str, limit: int, database: str | None = None, schema: str | None = None
    ) -> str:
        parts = [f'"{p}"' for p in (database, schema, table) if p]
        return f"SELECT * FROM {'.'.join(parts)} LIMIT {limit}"

    def format_table_name(self, schema: str | None, table: str) -> str:
        return f'"{schema}"."{table}"' if schema else f'"{table}"'


class ExplodingDialect:
    """Dialect whose build_select_query raises — verifies graceful degradation."""

    def quote_identifier(self, name: str) -> str:
        return f'"{name}"'

    def build_select_query(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("boom")

    def format_table_name(self, schema: str | None, table: str) -> str:
        return table


@dataclass
class _FakeConfig:
    name: str


class TestTable:
    def test_table_with_database_schema_name_identity(self) -> None:
        node = TableNode(database="mydb", schema="public", name="users")
        result = resolve_node_names("table", node, IdentityDialect())
        assert result is not None
        assert result.name == "users"
        assert result.dotted == "mydb.public.users"
        assert result.qualified == "mydb.public.users"
        assert result.select_snippet == "SELECT * FROM mydb.public.users LIMIT 100"

    def test_table_with_database_schema_name_double_quote(self) -> None:
        node = TableNode(database="mydb", schema="public", name="users")
        result = resolve_node_names("table", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "users"
        assert result.dotted == "mydb.public.users"
        assert result.qualified == '"mydb"."public"."users"'
        assert result.select_snippet == 'SELECT * FROM "mydb"."public"."users" LIMIT 100'

    def test_table_name_only_no_db_no_schema(self) -> None:
        node = TableNode(database=None, schema="", name="users")
        result = resolve_node_names("table", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "users"
        assert result.dotted == "users"
        assert result.qualified == '"users"'
        assert result.select_snippet == 'SELECT * FROM "users" LIMIT 100'

    def test_table_with_no_dialect_falls_back_to_dotted(self) -> None:
        node = TableNode(database="mydb", schema="public", name="users")
        result = resolve_node_names("table", node, None)
        assert result is not None
        assert result.qualified == result.dotted == "mydb.public.users"
        assert result.select_snippet is None  # no dialect → no build_select

    def test_table_build_select_exception_leaves_other_fields(self) -> None:
        node = TableNode(database="mydb", schema="public", name="users")
        result = resolve_node_names("table", node, ExplodingDialect())
        assert result is not None
        assert result.name == "users"
        assert result.dotted == "mydb.public.users"
        assert result.qualified == '"mydb"."public"."users"'
        assert result.select_snippet is None


class TestView:
    def test_view_shape_matches_table(self) -> None:
        node = ViewNode(database="mydb", schema="public", name="user_view")
        result = resolve_node_names("view", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "user_view"
        assert result.qualified == '"mydb"."public"."user_view"'
        assert result.select_snippet == 'SELECT * FROM "mydb"."public"."user_view" LIMIT 100'


class TestColumn:
    def test_column_four_parts_no_select(self) -> None:
        node = ColumnNode(database="mydb", schema="public", table="users", name="email")
        result = resolve_node_names("column", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "email"
        assert result.dotted == "mydb.public.users.email"
        assert result.qualified == '"mydb"."public"."users"."email"'
        assert result.select_snippet is None

    def test_column_no_database(self) -> None:
        node = ColumnNode(database=None, schema="public", table="users", name="email")
        result = resolve_node_names("column", node, IdentityDialect())
        assert result is not None
        assert result.dotted == "public.users.email"


class TestSchema:
    def test_schema_two_parts(self) -> None:
        node = SchemaNode(database="mydb", schema="public", folder_type="tables")
        result = resolve_node_names("schema", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "public"
        assert result.dotted == "mydb.public"
        assert result.qualified == '"mydb"."public"'
        assert result.select_snippet is None

    def test_schema_no_database(self) -> None:
        node = SchemaNode(database=None, schema="public", folder_type="tables")
        result = resolve_node_names("schema", node, IdentityDialect())
        assert result is not None
        assert result.dotted == "public"


class TestDatabaseAndConnection:
    def test_database_single_part(self) -> None:
        node = DatabaseNode(name="mydb")
        result = resolve_node_names("database", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "mydb"
        assert result.dotted == "mydb"
        assert result.qualified == '"mydb"'
        assert result.select_snippet is None

    def test_connection_uses_config_name(self) -> None:
        node = ConnectionNode(config=_FakeConfig(name="my-conn"))  # type: ignore[arg-type]
        result = resolve_node_names("connection", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "my-conn"
        assert result.dotted == "my-conn"
        assert result.qualified == '"my-conn"'
        assert result.select_snippet is None


class TestIndexTriggerSequenceProcedure:
    def test_index_with_database(self) -> None:
        node = IndexNode(database="mydb", name="idx_users_email", table_name="users")
        result = resolve_node_names("index", node, DoubleQuoteDialect())
        assert result is not None
        assert result.name == "idx_users_email"
        assert result.dotted == "mydb.idx_users_email"
        assert result.qualified == '"mydb"."idx_users_email"'
        assert result.select_snippet is None

    def test_index_no_database(self) -> None:
        node = IndexNode(database=None, name="idx_users_email", table_name="users")
        result = resolve_node_names("index", node, IdentityDialect())
        assert result is not None
        assert result.dotted == "idx_users_email"

    def test_trigger_with_database(self) -> None:
        node = TriggerNode(database="mydb", name="trg_users_ai", table_name="users")
        result = resolve_node_names("trigger", node, DoubleQuoteDialect())
        assert result is not None
        assert result.dotted == "mydb.trg_users_ai"
        assert result.qualified == '"mydb"."trg_users_ai"'
        assert result.select_snippet is None

    def test_sequence(self) -> None:
        node = SequenceNode(database="mydb", name="users_id_seq")
        result = resolve_node_names("sequence", node, IdentityDialect())
        assert result is not None
        assert result.dotted == "mydb.users_id_seq"
        assert result.select_snippet is None

    def test_procedure(self) -> None:
        node = ProcedureNode(database="mydb", name="sp_refresh")
        result = resolve_node_names("procedure", node, DoubleQuoteDialect())
        assert result is not None
        assert result.qualified == '"mydb"."sp_refresh"'
        assert result.select_snippet is None


class TestEmptyKinds:
    @pytest.mark.parametrize(
        ("kind", "data"),
        [
            ("folder", FolderNode(folder_type="tables")),
            ("loading", LoadingNode()),
            ("connection_folder", ConnectionFolderNode(name="Work")),
        ],
    )
    def test_empty_kinds_return_none(self, kind: str, data: Any) -> None:
        assert resolve_node_names(kind, data, DoubleQuoteDialect()) is None


class TestReturnType:
    def test_result_is_frozen_dataclass(self) -> None:
        node = TableNode(database=None, schema="", name="users")
        result = resolve_node_names("table", node, IdentityDialect())
        assert isinstance(result, NodeNames)
        with pytest.raises(AttributeError):
            result.name = "other"  # type: ignore[misc]
