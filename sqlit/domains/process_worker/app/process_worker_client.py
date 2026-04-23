"""Process-based query execution client."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from multiprocessing import get_context
import os
import sys
from multiprocessing.connection import Connection
from typing import Any

from sqlit.domains.connections.domain.config import ConnectionConfig
from sqlit.domains.query.app.query_service import NonQueryResult, QueryResult
from sqlit.domains.connections.providers.adapters.base import ColumnInfo

from .process_worker import run_process_worker


class WorkerPipeClosedError(RuntimeError):
    """Raised when the worker subprocess has closed its end of the pipe."""


@dataclass
class ProcessQueryOutcome:
    """Outcome for a process-executed query."""

    result: QueryResult | NonQueryResult | None
    elapsed_ms: float
    cancelled: bool = False
    error: str | None = None


class ProcessWorkerClient:
    """Runs queries in a separate process."""

    def __init__(self) -> None:
        import tempfile

        self._conn: Connection | None = None
        self._process = None
        # Tempfile receives the worker's stderr; we tail it when surfacing
        # pipe-closed errors so segfaults/import-time crashes aren't silent.
        # Created up-front because we pass the path into the spawn args.
        # If spawning fails we unlink it in the `except` below — otherwise a
        # failed init leaves orphaned `sqlit-worker-*.log` files on disk.
        fd, self._stderr_log_path = tempfile.mkstemp(prefix="sqlit-worker-", suffix=".log")
        os.close(fd)
        try:
            try:
                self._start_with_context(get_context("spawn"))
            except Exception as exc:
                self._maybe_fallback_start(exc)
            self._send_lock = threading.Lock()
            self._execute_lock = threading.Lock()
            self._next_id = 1
            self._closed = False
            self._current_id: int | None = None
            if self._conn is None or self._process is None:
                raise RuntimeError("Failed to start process worker.")
        except BaseException:
            if self._stderr_log_path:
                try:
                    os.unlink(self._stderr_log_path)
                except Exception:
                    pass
                self._stderr_log_path = None
            raise

    def _start_with_context(self, ctx: Any) -> None:
        parent_conn, child_conn = ctx.Pipe(duplex=True)
        self._conn = parent_conn
        self._process = ctx.Process(
            target=run_process_worker,
            args=(child_conn, self._stderr_log_path),
            daemon=True,
        )
        self._process.start()

    def _worker_death_reason(self) -> str:
        """Summarize why the worker subprocess is unreachable."""
        parts: list[str] = []
        process = self._process
        if process is not None:
            exitcode = getattr(process, "exitcode", None)
            if exitcode is not None:
                parts.append(f"worker exit code {exitcode}")
        path = self._stderr_log_path
        if path:
            try:
                with open(path) as fh:
                    tail = fh.read().strip()
                if tail:
                    # Keep the message short enough to fit in a notify popup.
                    if len(tail) > 400:
                        tail = "..." + tail[-400:]
                    parts.append(tail)
            except Exception:
                pass
        return "; ".join(parts) if parts else "worker subprocess terminated unexpectedly"

    def _maybe_fallback_start(self, error: Exception) -> None:
        if not isinstance(error, ValueError):
            raise error
        message = str(error)
        if "fds_to_keep" not in message:
            raise error
        if os.name != "posix" or sys.platform.startswith("win"):
            raise error
        try:
            self._start_with_context(get_context("fork"))
        except Exception:
            raise error

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._send({"type": "shutdown"})
        except Exception:
            pass
        try:
            if self._conn is not None:
                self._conn.close()
        except Exception:
            pass
        if self._process is not None:
            if self._process.is_alive():
                self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.terminate()
        # Best-effort cleanup of the stderr log file.
        path = self._stderr_log_path
        self._stderr_log_path = None
        if path:
            try:
                os.unlink(path)
            except Exception:
                pass

    def cancel_current(self) -> None:
        query_id = self._current_id
        if query_id is None:
            return
        try:
            self._send({"type": "cancel", "id": query_id})
        except Exception:
            pass

    def execute(self, query: str, config: ConnectionConfig, max_rows: int | None) -> ProcessQueryOutcome:
        with self._execute_lock:
            if self._closed:
                return ProcessQueryOutcome(result=None, elapsed_ms=0, error="Worker is closed.")

            query_id = self._next_id
            self._next_id += 1
            self._current_id = query_id

            payload = {
                "type": "exec",
                "id": query_id,
                "query": query,
                "config": config.to_dict(include_passwords=True),
                "db_type": config.db_type,
                "max_rows": max_rows,
            }
            try:
                self._send(payload)
            except WorkerPipeClosedError:
                return ProcessQueryOutcome(
                    result=None, elapsed_ms=0, error=self._worker_death_reason()
                )

            try:
                while True:
                    try:
                        message = self._conn.recv()
                    except (EOFError, BrokenPipeError, OSError):
                        self._closed = True
                        return ProcessQueryOutcome(
                            result=None, elapsed_ms=0, error=self._worker_death_reason()
                        )
                    if message.get("id") != query_id:
                        continue
                    msg_type = message.get("type")
                    if msg_type == "result":
                        return ProcessQueryOutcome(
                            result=message.get("result"),
                            elapsed_ms=float(message.get("elapsed_ms", 0)),
                        )
                    if msg_type == "cancelled":
                        return ProcessQueryOutcome(result=None, elapsed_ms=0, cancelled=True)
                    if msg_type == "error":
                        return ProcessQueryOutcome(
                            result=None,
                            elapsed_ms=0,
                            error=str(message.get("message", "Worker error.")),
                        )
            finally:
                self._current_id = None

    def list_columns(
        self,
        *,
        config: ConnectionConfig,
        database: str | None,
        schema: str | None,
        name: str,
    ) -> ProcessSchemaOutcome:
        with self._execute_lock:
            if self._closed:
                return ProcessSchemaOutcome(columns=None, error="Worker is closed.")

            query_id = self._next_id
            self._next_id += 1
            self._current_id = query_id

            payload = {
                "type": "schema",
                "op": "columns",
                "id": query_id,
                "config": config.to_dict(include_passwords=True),
                "db_type": config.db_type,
                "database": database,
                "schema": schema,
                "name": name,
            }
            try:
                self._send(payload)
            except WorkerPipeClosedError:
                return ProcessSchemaOutcome(columns=None, error=self._worker_death_reason())

            try:
                while True:
                    try:
                        message = self._conn.recv()
                    except (EOFError, BrokenPipeError, OSError):
                        self._closed = True
                        return ProcessSchemaOutcome(columns=None, error=self._worker_death_reason())
                    if message.get("id") != query_id:
                        continue
                    msg_type = message.get("type")
                    if msg_type == "schema" and message.get("op") == "columns":
                        columns = message.get("columns")
                        if isinstance(columns, list):
                            return ProcessSchemaOutcome(columns=columns)
                        return ProcessSchemaOutcome(columns=[])
                    if msg_type == "cancelled":
                        return ProcessSchemaOutcome(columns=None, cancelled=True)
                    if msg_type == "error":
                        return ProcessSchemaOutcome(
                            columns=None,
                            error=str(message.get("message", "Worker error.")),
                        )
            finally:
                self._current_id = None

    def list_folder_items(
        self,
        *,
        config: ConnectionConfig,
        database: str | None,
        folder_type: str,
    ) -> ProcessFolderOutcome:
        with self._execute_lock:
            if self._closed:
                return ProcessFolderOutcome(items=None, error="Worker is closed.")

            query_id = self._next_id
            self._next_id += 1
            self._current_id = query_id

            payload = {
                "type": "schema",
                "op": "folder_items",
                "id": query_id,
                "config": config.to_dict(include_passwords=True),
                "db_type": config.db_type,
                "database": database,
                "folder_type": folder_type,
            }
            try:
                self._send(payload)
            except WorkerPipeClosedError:
                return ProcessFolderOutcome(items=None, error=self._worker_death_reason())

            try:
                while True:
                    try:
                        message = self._conn.recv()
                    except (EOFError, BrokenPipeError, OSError):
                        self._closed = True
                        return ProcessFolderOutcome(items=None, error=self._worker_death_reason())
                    if message.get("id") != query_id:
                        continue
                    msg_type = message.get("type")
                    if msg_type == "schema" and message.get("op") == "folder_items":
                        items = message.get("items")
                        if isinstance(items, list):
                            return ProcessFolderOutcome(items=items)
                        return ProcessFolderOutcome(items=[])
                    if msg_type == "cancelled":
                        return ProcessFolderOutcome(items=None, cancelled=True)
                    if msg_type == "error":
                        return ProcessFolderOutcome(
                            items=None,
                            error=str(message.get("message", "Worker error.")),
                        )
            finally:
                self._current_id = None

    def _send(self, payload: dict[str, Any]) -> None:
        with self._send_lock:
            if self._closed or self._conn is None:
                raise WorkerPipeClosedError("Worker connection unavailable.")
            try:
                self._conn.send(payload)
            except (BrokenPipeError, EOFError, OSError) as exc:
                # Pipe went away — worker subprocess likely died. Mark the
                # client closed so follow-up calls short-circuit cleanly
                # instead of stacking broken-pipe errors.
                self._closed = True
                raise WorkerPipeClosedError(f"Worker pipe closed: {exc}") from exc

    @property
    def is_closed(self) -> bool:
        """Whether the pipe to the worker has been closed (dead worker)."""
        if self._closed:
            return True
        process = self._process
        if process is not None and not process.is_alive():
            self._closed = True
            return True
        return False


@dataclass
class ProcessSchemaOutcome:
    """Outcome for a process-executed schema request."""

    columns: list[ColumnInfo] | None
    cancelled: bool = False
    error: str | None = None


@dataclass
class ProcessFolderOutcome:
    """Outcome for a process-executed folder listing request."""

    items: list[Any] | None
    cancelled: bool = False
    error: str | None = None
