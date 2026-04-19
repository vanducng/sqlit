# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`sqlit` (PyPI: `sqlit-tui`) — a Textual-based terminal UI for 25+ SQL databases. Entry point: `sqlit.cli:main`. Requires Python 3.10+.

## Common Commands

### Install (dev)
```bash
pip install -e ".[dev]"        # core + test + lint
pip install -e ".[dev,all]"    # + every DB driver (needed for full integration suite)
```
`uv` is the CI package manager: `uv sync --group test --no-dev`, `uv run pytest ...`.

### Run locally
```bash
sqlit                          # launch TUI, pick a saved connection
sqlit --mock=sqlite-demo       # launch against mock adapter (no real DB)
sqlit -c "Name"                # open specific saved connection
sqlit query -c "Name" -q "SELECT ..."   # non-interactive CLI mode
sqlit postgresql://user:pass@host/db    # URL-based ad-hoc connect
```

### Tests
```bash
pytest tests/ -v -k sqlite                                   # no Docker required
pytest tests/cli/ -v                                         # CLI E2E (subprocess)
pytest tests/ -v                                             # full suite (needs Docker)
pytest tests/integration/docker_detect/ -v --run-docker-container
pytest tests/test_postgresql.py::test_name -v                # single test
```
Spin up backing DBs: `docker compose -f infra/docker/docker-compose.test.yml up -d` (add `--profile enterprise` for Db2/Trino/Presto/Oracle 11g). Containers are reusable across runs. Test env vars per DB are documented in `CONTRIBUTING.md`.

The CI `test-unit` job explicitly `--ignore`s every real-DB test file — treat `tests/test_<db>.py` as integration-only and prefer pure-unit tests elsewhere.

### Lint / typecheck / build
```bash
ruff check .           # rules: E,F,I,UP,B,S,C90,SIM,RUF; line-length 240; mccabe max-complexity 25
mypy sqlit             # strict: disallow_untyped_defs, warn_return_any, strict_optional
python -m build        # sdist + wheel via hatchling (version from VCS tag)
nix build .#sqlit      # flake build (mirrored in CI)
```

## Architecture

### Layout
Source lives in `sqlit/` (not `src/sqlit/`). Three top-level layers:

- `sqlit/cli.py` — argparse entry: parses URLs/subcommands, builds runtime, dispatches to TUI or CLI subcommands (`connections`, `connect`, `query`).
- `sqlit/core/` — app-wide modal input machinery shared by every screen: `vim.py` (motion engine), `keymap.py`, `key_router.py`, `binding_contexts.py`, `input_context.py`, `leader_commands.py`, `state_base.py`, `connection_manager.py`.
- `sqlit/domains/<domain>/` — feature slices. Each domain follows the same sub-layout where applicable:
  - `domain/` — pure data/config models (e.g. `ConnectionConfig`, `DatabaseType`, `AuthType`)
  - `app/` — orchestration, services, flows (no Textual imports)
  - `store/` — persistence (JSON + OS keyring)
  - `ui/` — Textual widgets/screens
  - `state/` — screen-local state machines
  - `cli/` — argparse wiring for CLI subcommands
  - `providers/` (connections only) — per-DB adapter packages
- `sqlit/shared/` — cross-domain infra:
  - `app/runtime.py`, `app/services.py` — `RuntimeConfig` + `build_app_services` DI container
  - `core/protocols.py` — `ConnectionStoreProtocol`, `HistoryStoreProtocol`, `ProviderFactoryProtocol`, etc. (the seams tests mock against)
  - `core/processes.py` — sync/async subprocess runners (injectable for tests)
  - `ui/` — shared widgets (autocomplete, tables, dialogs, footer, text area, value view)

### Domains
- `connections/` — the heaviest domain. `providers/` has one package per DB (`postgresql/`, `mssql/`, `bigquery/`, `duckdb/`, `snowflake/`, `surrealdb/`, `osquery/`, …) plus `adapters/`, `catalog.py`, `registry.py`, `driver.py` (dependency resolution & install strategy), `docker.py`, `explorer_nodes.py`, `schema_catalog.py`. `app/` handles connection flow, credential storage (OS keyring via `keyring`), SSH tunneling (`sshtunnel`+`paramiko` behind the `ssh` extra), cloud discovery, mock adapters.
- `query/` — query editor + execution. `completion/` is a per-statement-type autocomplete engine (`create_table.py`, `insert.py`, `update.py`, …; `completion.py` is C901-exempt). `app/query_runner.py` + `cancellable.py` + `multi_statement.py` + `transaction.py` drive execution; `editing/` integrates with `core/vim.py`.
- `explorer/` — DB tree (tables/views/procedures/indexes/triggers/sequences).
- `results/` — result grid, formatters (CSV/JSON), filter/fuzzy search.
- `shell/` — the TUI shell/root screen that wires the other domains together.
- `process_worker/` — background work + progress UI.

### Provider pattern
Adding a new database means: drop a package under `sqlit/domains/connections/providers/<db>/` implementing the adapter protocol, register it in `catalog.py`/`registry.py`, declare its driver in `driver.py` (for the auto-install wizard), add an optional-dependency extra in `pyproject.toml`, and add a `tests/test_<db>.py` integration file (plus a compose service in `infra/docker/docker-compose.test.yml` when possible).

### Runtime composition
`cli.py` → `RuntimeConfig` (flags, mock config, startup profiler) → `build_app_services()` in `shared/app/services.py` wires stores, process runners, provider factories, system probe, and driver resolver. Tests substitute any of these via the protocols in `shared/core/protocols.py` and the fakes in `shared/core/system_probe_fake.py` / `FixedResult*Runner`.

### Mocking
`sqlit --mock=<profile>` routes through `domains/connections/app/mock_*.py` + top-level `sqlit/mock_settings.py`. Use this (and `fakesnow` for Snowflake) to develop UI without real DBs.

### Config location
`$XDG_CONFIG_HOME/sqlit/` (default `~/.config/sqlit/`), overridable with `SQLIT_CONFIG_DIR`. Connection metadata → `connections.json`; passwords → OS keyring. Legacy `~/.sqlit/` is auto-migrated on first run.

## Conventions specific to this repo

- Textual `BINDINGS` as mutable class defaults are intentional — `RUF012` is globally ignored. Follow the framework convention.
- Many `S*` bandit rules are ignored because this is a SQL tool and a CLI: raw SQL strings (`S608`), `subprocess` without shell (`S603`), partial executable paths (`S607`), and `os.execv` for restart (`S606`) are all expected. Don't "fix" them.
- `try/except: pass` is used deliberately to keep the TUI from crashing; `S110` and `SIM105` are ignored. Don't replace with `contextlib.suppress` for style.
- Vision / scope (see `CONTRIBUTING.md` "Vision" section): every feature must serve **C**onnect / **E**xplore / **Q**uery / **R**esults and be **E**asy/**A**esthetic/**F**un/**F**ast. Settings/toggles/preferences are avoided by design — don't add feature flags. Advanced features go behind `<space>` leader or `?` help, never on the main toolbar.
- Keybindings favor vim tradition; `Ctrl+` is reserved for places without insert/normal modal context (modals). First-letter mnemonics for pane focus (`e`/`q`/`r`).
