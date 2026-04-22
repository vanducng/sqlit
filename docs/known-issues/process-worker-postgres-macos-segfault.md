---
title: Process worker SIGSEGV with psycopg2 on macOS
status: known-issue
severity: medium
area: process-worker
affected-dbs: postgresql
affected-os: darwin
first-observed: 2026-04-23
---

# Process worker SIGSEGV with psycopg2 on macOS

## Symptom

When connecting to a PostgreSQL database on macOS and expanding a folder in
the Explorer (Tables, Views, …), the user sees:

```
Error loading: worker exit code -11; <traceback or empty>
```

Exit code `-11` is UNIX signal 11 — **SIGSEGV**, a segmentation fault inside
the subprocess. The main-process connection to the same database works
correctly; the crash only happens inside the spawned `process_worker`
subprocess.

Happy-path behaviour (`SQLIT_PROCESS_WORKER=0`, SQLite, DuckDB, BigQuery, …)
is unaffected.

## Root cause

`sqlit` runs schema listings and queries in a child process via
`multiprocessing.get_context("spawn")`. Under `spawn`, Python re-imports
every module from scratch in the subprocess.

`psycopg2-binary` ships its own statically linked `libpq` + OpenSSL. The
re-import path in the fresh subprocess triggers a double-init / ABI
mismatch inside those C libraries when the very first `PQconnectdb` is
attempted — typically during TLS / SCRAM-SHA-256 negotiation or during
OpenSSL's global state setup.

Python cannot catch a SIGSEGV — the subprocess dies before any `except`
clause runs, so the worker's stderr log is empty and the parent only sees
the exit code.

The issue is reproducible with:

- Python 3.14 + psycopg2-binary 2.9.x on macOS (darwin-arm64 and -x86_64)
- Spawn start method (the default on macOS since Python 3.8)
- Any libpq build that links against the system's OpenSSL on macOS
  Sequoia+ (the OS keychain stack interacts badly with re-init)

## Why the current client-side guards don't help

We added defensive handling in PR #10:

- Worker-side top-level `try/except` (catches Python exceptions before the
  pipe closes).
- Client-side `BrokenPipeError` / `EOFError` catching in `_send` / `recv`.
- Worker stderr redirected to a per-subprocess tempfile for post-mortem
  diagnostics.
- Session-level `_process_worker_disabled` flag so a dead worker isn't
  respawned every expansion, which would just crash again.

These improvements surface the real exit code and prevent error-spam, but
**none of them can prevent the SIGSEGV**. Once libpq crashes inside the
child, the subprocess is gone. Recovery happens on the next expand via the
existing `client is None` → in-process schema-service fallback path.

## Workarounds users can apply today

- **Disable the worker process entirely** (trade-off: long queries block the
  TUI, cancellation is coarser):
  ```bash
  SQLIT_PROCESS_WORKER=0 sqlit
  ```
- **Use a different PG driver in your venv.** Installing `psycopg` (v3)
  alongside psycopg2-binary does not automatically route the worker
  through it — see "Proposed fixes" below.

## Proposed fixes (future work)

Ordered by effort:

1. **Provider-level opt-out on macOS.**
   Add `supports_process_worker = False` on the postgres adapter **only
   when `sys.platform == "darwin"`**. Worker would be used on Linux/Windows
   (where this segfault doesn't happen) and skipped on macOS. Low risk,
   small diff, clean default UX for macOS users.
   - Files: `sqlit/domains/connections/providers/postgresql/adapter.py`
     (or equivalent) — add a platform check to the `supports_process_worker`
     property.

2. **Migrate to `psycopg` (v3).**
   Psycopg3 has a better-behaved C extension split (`psycopg` pure Python
   +optional `psycopg-c`/`psycopg-binary`). Its forking/spawning story is
   more robust than psycopg2. Modernizes the driver and removes the root
   cause on macOS too. Larger change — connection-string parsing, cursor
   API, parameter style remain similar but some defaults differ.
   - Files: `sqlit/domains/connections/providers/postgresql/*`,
     `pyproject.toml` (swap `psycopg2-binary` → `psycopg[binary]`).

3. **Force-preload libpq in the subprocess before any import.**
   Hypothesis: importing `ssl` or `psycopg2` once in the parent before
   `spawn` and setting `multiprocessing.set_forkserver_preload([...])`
   might avoid the double-init. Unverified — psycopg2-binary bundles
   its own OpenSSL so preloading in the parent may or may not help.
   Worth a small experiment before committing to options 1/2.

4. **Switch macOS to `forkserver` start method.**
   `forkserver` starts a lightweight helper process once, then `fork()`s
   children from there. This avoids re-running `__main__` in each worker
   but still gives a clean process. Some native libs behave better here.
   Risk: `fork()` on macOS has its own set of known hangs (Objective-C
   runtime, Grand Central Dispatch), historically fixed by
   `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`. Needs testing.

## Action items

- [ ] Short-term: land option 1 (macOS opt-out for postgres).
- [ ] Medium-term: evaluate option 2 (psycopg v3 migration). Open a
      dedicated plan once we decide to do it.
- [ ] Add a telemetry event `process_worker.segfault` so we know how
      common this is across installs.

## References

- psycopg2 known fork/spawn issues:
  https://www.psycopg.org/docs/usage.html#thread-and-process-safety
- CPython multiprocessing spawn semantics:
  https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
- PR that added the diagnostics: #10
