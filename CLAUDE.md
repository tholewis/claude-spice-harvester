# Claude Spice Harvester — CLAUDE.md

macOS menu bar app that tracks Claude Code token usage from `~/.claude/`. Dune-themed. Written in Python with `rumps`.

## Running

```bash
python3 claude_spice_harvester.py
```

Requires: `pip install rumps` (and optionally `pyobjc` for color support — usually pre-installed on macOS).

## File structure

```
claude_spice_harvester.py  — entire app (data layer + HTML dashboard + menu bar app)
build_app.sh               — packages into a standalone ClaudeSpiceHarvester.app via PyInstaller
docs/README.md     — user-facing documentation
```

## Key architecture

**Data layer** (`load_all_usage` → `aggregate_records`): scans `~/.claude/projects/**/*.jsonl` for JSONL entries with `{type: "assistant", message: {usage: {...}}}`. Aggregates into totals, today, this week, and the current 5-hour UTC window (approximating Claude Pro's session cycle).

**Session window**: Claude Pro resets every 5 hours on UTC boundaries (0h, 5h, 10h, 15h, 20h). `get_session_window()` computes the current window; `session_reset_in` is seconds until it rolls over.

**Gauge percentage**: there's no local API for the real plan limit, so the gauge shows session tokens as a fraction of the peak daily token count from the past 7 days.

**HTML dashboard** (`HTML_TEMPLATE` + `build_html`): Dune-themed page opened in the browser via `file://`. Uses a horizontal progress bar for the session gauge (replaced a circular SVG arc that had contrast issues).

**Template substitution**: the HTML template contains CSS with `{ }` blocks, so `str.format()` breaks it. Always use the `substitutions` dict with explicit `str.replace()` calls. Never switch to `.format()`.

**Menu bar colors** (`_paint`): uses `NSAttributedString` from AppKit. Setting `item.title = ...` clears any attributed string, so `_paint()` must be called again after every title update in `refresh_data()`. Items with `callback=None` are disabled (grayed out) by macOS — use `lambda _: None` to keep them enabled while still non-interactive.

## Dune color palette

| Constant   | RGB (0–1)              | Role                   |
|------------|------------------------|------------------------|
| `_C_GOLD`  | 0.91, 0.72, 0.29       | Session (bright gold)  |
| `_C_SAND`  | 0.83, 0.65, 0.38       | Today / pct sub-line   |
| `_C_AMBER` | 0.72, 0.54, 0.23       | Week / reset sub-line  |
| `_C_SPICE` | 0.77, 0.35, 0.12       | All-time (spice red)   |
| `_C_ACTION`| 0.79, 0.58, 0.17       | Open / Refresh items   |
| `_C_DANGER`| 0.60, 0.22, 0.09       | Quit item              |
