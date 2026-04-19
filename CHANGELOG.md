# Changelog

All notable user-facing changes to sqlit.

## Unreleased

### Changed

- **Breaking:** `Enter` in the query editor now runs only the statement under the
  cursor (split by `;`), matching DataGrip / DBeaver / VS Code SQL Tools. Use
  `<space>ga` (or the existing `<space>gr`) to run all statements in the buffer.
  `Ctrl+Enter` in INSERT mode follows the same rule and keeps the cursor in
  INSERT mode after running.

### Added

- `<space>ga` leader alias for "run all statements".
- SSH tab now discovers aliases from `~/.ssh/config` with ProxyJump support.
- Subtle background tint on the lines of the statement under the cursor when
  the buffer contains two or more statements, so you can see what `Enter` will
  execute before pressing it.
