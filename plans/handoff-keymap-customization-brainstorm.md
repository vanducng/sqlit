# Handoff: Keymap Customization — Brainstorm Next Session

## How to use this file

Paste the **Prompt** section below into a new Claude Code session after
running `/brainstorm`. All context needed is included inline so the agent
does not have to re-scout.

---

## Prompt

> I need to design a **user-facing keymap customization path** for sqlit. Previous attempts were either absent (programmatic-only `set_keymap()`) or too complex for end users (a `SQLIT_KEYMAP_MODULE` env var pointing at a Python module that calls `install_keymap()` — reverted as too much ceremony). Both failure modes are on record. Please brainstorm 2–3 options with brutal tradeoff analysis and recommend one.
>
> ### Constraint: the "no preferences" project ethos
>
> sqlit's `CLAUDE.md` says:
>
> > Vision / scope: every feature must serve **C**onnect / **E**xplore / **Q**uery / **R**esults and be **E**asy/**A**esthetic/**F**un/**F**ast. Settings/toggles/preferences are avoided by design — don't add feature flags. Advanced features go behind `<space>` leader or `?` help, never on the main toolbar.
>
> So a full settings UI or `~/.config/sqlit/keymap.toml` is philosophically risky. BUT: real users want to rebind pane focus keys (`e` / `q` / `r` → `1` / `2` / `3`) without forking. The tension is: **no preferences** vs. **legitimate rebinding demand**.
>
> ### Concrete user request that triggered this
>
> "I want to replace `e` / `q` / `r` with `1` / `2` / `3` for pane focus."
>
> That is the one concrete customization request on the table. Any solution that makes THIS simple is a win; anything more complex is overkill.
>
> ### Existing primitives (already in the codebase)
>
> - `sqlit/core/keymap.py` — `KeymapProvider` ABC, `DefaultKeymapProvider` with hardcoded `_build_action_keys()` / `_build_chords()` / `_build_leader_commands()`. Global `get_keymap()` / `set_keymap()` / `reset_keymap()` singleton pattern.
> - `sqlit/core/action_validation.py` — walks every registered action and asserts the app exposes `action_<name>`. Catches typos at startup.
> - `ChordDef` (timed sequences like `jk` → exit INSERT) is dispatched inline in `QueryTextArea._try_dispatch_chord`.
> - Leader menus (`<space>+x`, `gg`, `dd`) have their own `leader_pending` machinery in `key_router.py` + `leader_commands.py`.
> - Pane focus keys are plain `ActionKeyDef` entries: `ActionKeyDef("e", "focus_explorer", "navigation")` etc. in `keymap.py:428-430`. A subclass that rewrites `_build_action_keys()` can already override them programmatically — the *seam* exists; the *user-facing loader* is what's missing.
>
> ### Options to debate (at minimum)
>
> 1. **Accept the status quo** — no user override. Users who want it fork or run patched builds. Honest to the "no preferences" ethos.
> 2. **Minimal declarative override** — a single env var `SQLIT_REBIND="focus_explorer=1,focus_query=2,focus_results=3"` (comma-separated `action=key` pairs). Action-name based, not file-based. Validated against the action surface. Small and discoverable. No Python import required.
> 3. **Opt-in TOML** — `~/.config/sqlit/keymap.toml` with a `[bindings]` table. More discoverable but adds a parsing surface and schema versioning burden.
> 4. **Python module loader** (the reverted approach) — full power, too much ceremony for the common case.
> 5. **In-app rebind UI** — leader menu `<space>+k` opens a rebinder. Contradicts "no preferences panels" but stays inside the TUI.
> 6. **Hybrid: env var for common case + module for power users** — two tiers. More code, more docs, but covers everyone.
>
> ### Tradeoff axes to rate each option against
>
> | Axis | Why it matters |
> |---|---|
> | One-line usage? | The 1/2/3 pane-key ask should be literally one line. |
> | "No preferences" philosophy compliance | Project ethos constraint. |
> | Discoverability | Users must find it without reading source. |
> | Failure mode on typos | Silent misbehavior = hours wasted. Must error loudly. |
> | Schema / migration cost | TOML config needs versioning; env var doesn't. |
> | Power-user escape hatch | Rare users want to add chords, not just rebind. |
> | Implementation LOC | sqlit is lean; avoid adding 300 LOC for niche features. |
>
> ### Deliverables
>
> 1. 2–3 options, each scored on the axes above.
> 2. One recommendation with explicit rationale.
> 3. If recommending ship: rough LOC budget + which files change.
> 4. Flag any implicit assumptions you challenged.
> 5. Under 500 words.
>
> ### Referenced prior work
>
> - `plans/reports/brainstorm-260419-1139-extensible-keybindings.md` — original chord/keymap brainstorm (recommended Option B, which was later trimmed).
> - `plans/reports/research-260419-1211-chord-resolver-prior-art.md` — research into how Vim, Helix, VS Code, Textual, `better-escape.nvim` handle this. Key finding: **no one unifies well** — each editor picks a tradeoff.
> - PR `refactor/inline-chord-dispatch` — the trim that removed `SQLIT_KEYMAP_MODULE` after it was deemed too complex.

---

## What's already decided (don't re-litigate)

- **Chord resolver stays inlined** — decided in the trim refactor. Don't propose re-extracting it.
- **Leader menus stay separate** from chords — decided in the initial brainstorm. Don't propose unification.
- **`ChordDef` dataclass stays on `KeymapProvider`** — it's cheap structural clarity.
- **`set_keymap()` stays** as a test seam — it's the mechanism, the UX on top is what's open.

## What's explicitly open

- The user-facing loader mechanism (env var / TOML / CLI flag / in-app UI / none).
- Whether to add `--keymap-module` CLI flag for discoverability.
- Whether to document programmatic override in README for power users as a stopgap.
- Whether the "no preferences" rule should flex for keybindings specifically.

## Success criteria for the next brainstorm

A clear answer to: *"What does a sqlit user type to swap `e`/`q`/`r` for `1`/`2`/`3`, and does it align with the project ethos?"* — with the alternatives honestly compared.
