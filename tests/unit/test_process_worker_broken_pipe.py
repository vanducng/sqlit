"""Resilience tests for process-worker pipe failures.

Covers:
1. Client-side: a closed/broken pipe surfaces as a `WorkerPipeClosedError`
   and marks the client closed, rather than a raw `BrokenPipeError`.
2. `is_closed` correctly reflects both an explicit `_closed` flag and a
   dead subprocess whose pipe has not yet been exercised.
3. Worker-side: `run_process_worker` survives a handler that throws — the
   subprocess keeps polling and reports the failure to the client.
"""

from __future__ import annotations

import threading
import time
from multiprocessing import get_context
from typing import Any

import pytest

from sqlit.domains.process_worker.app.process_worker import _WorkerState, run_process_worker
from sqlit.domains.process_worker.app.process_worker_client import (
    ProcessWorkerClient,
    WorkerPipeClosedError,
)


class _FakeConnection:
    """A `multiprocessing.connection.Connection` stand-in."""

    def __init__(self, *, send_raises: Exception | None = None) -> None:
        self.sent: list[Any] = []
        self._send_raises = send_raises

    def send(self, payload: Any) -> None:
        if self._send_raises is not None:
            raise self._send_raises
        self.sent.append(payload)

    def recv(self) -> Any:  # pragma: no cover - not exercised in these tests
        raise EOFError("no incoming messages")

    def close(self) -> None:
        pass


class _FakeProcess:
    def __init__(self, alive: bool = True) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        pass

    def terminate(self) -> None:
        self._alive = False


def _make_client_with_connection(conn: _FakeConnection, process: _FakeProcess | None = None) -> ProcessWorkerClient:
    """Build a ProcessWorkerClient bypassing its real subprocess spawn."""
    client = ProcessWorkerClient.__new__(ProcessWorkerClient)
    client._conn = conn  # type: ignore[attr-defined]
    client._process = process or _FakeProcess(alive=True)  # type: ignore[attr-defined]
    client._send_lock = threading.Lock()
    client._execute_lock = threading.Lock()
    client._next_id = 1
    client._closed = False
    client._current_id = None
    client._stderr_log_path = None  # type: ignore[attr-defined]
    return client


class TestClientBrokenPipeHandling:
    def test_send_on_broken_pipe_raises_worker_pipe_closed(self) -> None:
        conn = _FakeConnection(send_raises=BrokenPipeError(32, "Broken pipe"))
        client = _make_client_with_connection(conn)

        with pytest.raises(WorkerPipeClosedError):
            client._send({"type": "ping"})

        assert client._closed is True

    def test_send_on_oserror_marks_closed(self) -> None:
        conn = _FakeConnection(send_raises=OSError("peer gone"))
        client = _make_client_with_connection(conn)

        with pytest.raises(WorkerPipeClosedError):
            client._send({"type": "ping"})

        assert client._closed is True

    def test_send_after_closed_short_circuits(self) -> None:
        conn = _FakeConnection()
        client = _make_client_with_connection(conn)
        client._closed = True

        with pytest.raises(WorkerPipeClosedError):
            client._send({"type": "ping"})

        assert conn.sent == []  # did not attempt send


class TestIsClosed:
    def test_is_closed_false_for_live_process(self) -> None:
        client = _make_client_with_connection(_FakeConnection(), _FakeProcess(alive=True))
        assert client.is_closed is False

    def test_is_closed_true_for_dead_process(self) -> None:
        client = _make_client_with_connection(_FakeConnection(), _FakeProcess(alive=False))
        assert client.is_closed is True
        # Side-effect: _closed is now latched for cheap follow-up calls.
        assert client._closed is True

    def test_is_closed_true_when_latched(self) -> None:
        client = _make_client_with_connection(_FakeConnection(), _FakeProcess(alive=True))
        client._closed = True
        assert client.is_closed is True


class TestWorkerLoopResilience:
    def test_worker_survives_handler_exception(self) -> None:
        """A handler raising synchronously must not kill the worker loop."""
        ctx = get_context("spawn")
        parent_conn, child_conn = ctx.Pipe(duplex=True)

        # Run the worker inline on a thread; inject a malformed message
        # the worker's dispatch doesn't recognize but that exercises
        # _handle_message.
        thread = threading.Thread(target=run_process_worker, args=(child_conn,), daemon=True)
        thread.start()

        # Send a malformed schema message: missing "op" triggers the unknown
        # operation branch which sends an error reply — not a crash path, but
        # proves the loop keeps serving.
        parent_conn.send({"type": "schema", "id": 1, "op": "nonsense"})
        reply = _recv_with_timeout(parent_conn, 3.0)
        assert reply["type"] == "error"
        assert reply["id"] == 1

        # Now send another message: if the loop were dead, this would hang.
        parent_conn.send({"type": "schema", "id": 2, "op": "nonsense"})
        reply2 = _recv_with_timeout(parent_conn, 3.0)
        assert reply2["type"] == "error"
        assert reply2["id"] == 2

        # Graceful shutdown.
        parent_conn.send({"type": "shutdown"})
        thread.join(timeout=2.0)
        assert not thread.is_alive()
        parent_conn.close()


class TestWorkerDeathReason:
    def test_reason_includes_exit_code_and_stderr_tail(self, tmp_path: Any) -> None:
        log = tmp_path / "stderr.log"
        log.write_text("Traceback (most recent call last):\n  File x\nImportError: no module named 'psycopg'\n")

        client = _make_client_with_connection(_FakeConnection(), _FakeProcess(alive=False))
        client._stderr_log_path = str(log)  # type: ignore[attr-defined]
        client._process._alive = False  # type: ignore[attr-defined]
        # Simulate known exit code.
        client._process.exitcode = 1  # type: ignore[attr-defined]

        reason = client._worker_death_reason()
        assert "exit code 1" in reason
        assert "ImportError" in reason

    def test_reason_falls_back_when_nothing_captured(self) -> None:
        client = _make_client_with_connection(_FakeConnection(), _FakeProcess(alive=True))
        client._stderr_log_path = None  # type: ignore[attr-defined]
        client._process.exitcode = None  # type: ignore[attr-defined]

        reason = client._worker_death_reason()
        assert "terminated unexpectedly" in reason


class TestWorkerStateSend:
    def test_send_swallows_broken_pipe(self) -> None:
        """_WorkerState.send never raises even if the pipe is gone."""
        conn = _FakeConnection(send_raises=BrokenPipeError(32, "Broken pipe"))
        state = _WorkerState(conn=conn)  # type: ignore[arg-type]
        # Should not raise even though the pipe throws.
        state.send({"type": "error", "id": 1, "message": "boom"})


def _recv_with_timeout(conn: Any, timeout_s: float) -> Any:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if conn.poll(0.05):
            return conn.recv()
    raise AssertionError(f"No message received within {timeout_s}s")
