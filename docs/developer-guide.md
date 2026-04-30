# Developer Guide — Claude Spice Harvester

## Overview

Claude Spice Harvester is a single-file macOS menu bar application that reads Claude Code's local JSONL session files and displays token usage statistics. It is written in Python using the `rumps` framework and presents data in a Dune-themed UI, both in the menu bar and via a generated HTML dashboard.

The entire application lives in one file: `claude_spice_harvester.py`. There is no build system, no server, and no network calls at runtime.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| macOS | 12 (Monterey) or later | Menu bar apps require macOS. Earlier versions are untested. |
| Python | 3.9+ | Ships with macOS; check with `python3 --version` |
| Claude Code | Any | Must have been used at least once so `~/.claude/` exists |
| `rumps` | Latest | `pip3 install rumps` — macOS menu bar framework |
| `pyobjc` | Latest | For colored menu text via `AppKit`. Usually pre-installed on macOS. Install manually with `pip3 install pyobjc` if menu colors are plain white. |
| PyInstaller | Latest | Only needed to build a standalone `.app`. `pip3 install pyinstaller` |

`rumps` is the only hard dependency. `pyobjc` degrades gracefully — the app runs without it, but menu items are uncolored. PyInstaller is only for packaging.

---

## Setup

### Running from source

```bash
pip3 install rumps
python3 claude_spice_harvester.py
```

`🏜` appears in the menu bar. No configuration required.

### Building a standalone .app

```bash
chmod +x build_app.sh
./build_app.sh
```

This calls PyInstaller with `--windowed --onefile` and copies the result to `./ClaudeSpiceHarvester.app`. Drag it to `/Applications`.

**Gatekeeper warning on first launch:** macOS will block the app because it is not signed. Fix once: Right-click → Open → Open.

### Configuration persistence

The selected theme is written to:

```
~/Library/Application Support/ClaudeSpiceHarvester/config.json
```

No other configuration is stored. The file is created automatically on first theme switch.

---

## Architecture

### File structure

```
claude_spice_harvester.py   — entire application
build_app.sh                — PyInstaller packaging script
docs/
  developer-guide.md        — this file
  llms.txt                  — LLM-readable summary
README.md                   — user-facing documentation
screenshots/                — PNG screenshots referenced by README.md
```

### Execution flow

```
main()
  └─ ClaudeSpiceHarvesterApp.__init__()
       ├─ load_config()              → reads ~/Library/.../config.json
       ├─ Builds rumps menu structure
       ├─ refresh_data(None)         → first data load
       └─ rumps.Timer(300s)          → schedules auto-refresh

refresh_data()
  ├─ load_all_usage()
  │    ├─ glob ~/.claude/**/*.jsonl + ~/Library/Application Support/Claude/**/*.jsonl
  │    ├─ parse_jsonl_file() per file
  │    ├─ extract_usage_from_entries() per file
  │    └─ aggregate_records()
  ├─ Updates menu item titles
  ├─ Re-applies NSAttributedString colors via _paint()
  └─ build_html() → writes to /tmp/claude_spice_harvester.html

open_dashboard()
  └─ webbrowser.open("file:///tmp/claude_spice_harvester.html")
```

---

## Data Layer

### Source files

The app scans these paths (deduplicating by absolute path):

1. `~/.claude/projects/**/*.jsonl`
2. `~/.claude/sessions/**/*.jsonl`
3. `~/.claude/conversations/**/*.jsonl`
4. `~/.claude/**/*.jsonl` (catch-all)
5. `~/Library/Application Support/Claude/**/*.jsonl` (if directory exists)

It also checks for `~/.claude/usage.json` and the equivalent in Application Support as supplemental sources.

### JSONL entry formats

Claude Code writes at least two entry shapes that the app handles:

**Type 1 — assistant message with nested usage:**
```json
{
  "type": "assistant",
  "timestamp": "2024-01-15T14:23:01.123Z",
  "message": {
    "model": "claude-sonnet-4-6",
    "usage": {
      "input_tokens": 1234,
      "output_tokens": 567,
      "cache_read_input_tokens": 890,
      "cache_creation_input_tokens": 100
    }
  }
}
```

**Type 2 — flat role entry:**
```json
{
  "role": "assistant",
  "timestamp": "2024-01-15T14:23:01.123Z",
  "model": "claude-sonnet-4-6",
  "usage": { ... }
}
```

**Type 3 — cost-keyed entry (older format):**
```json
{
  "costUSD": 0.0042,
  "inputTokens": 1234,
  "outputTokens": 567,
  "cacheReadTokens": 890,
  "cacheWriteTokens": 100,
  "model": "claude-sonnet-4-6",
  "timestamp": "2024-01-15T14:23:01.123Z"
}
```

Unrecognised entries are silently skipped. Malformed JSON lines are also silently skipped.

### Aggregation windows

`aggregate_records()` builds four token buckets:

| Bucket | Logic |
|---|---|
| `totals` | All records regardless of timestamp |
| `today` | Records whose local date equals `date.today()` |
| `week` | Records whose local date is within the last 7 days (today − 6 days) |
| `session` | Records whose UTC datetime falls within the current 5-hour window |

The session window is computed by `get_session_window()`:

```python
window_hour = (now.hour // 5) * 5   # 0, 5, 10, 15, or 20
start = now.replace(hour=window_hour, minute=0, second=0, microsecond=0)
end   = start + timedelta(hours=5)
```

This approximates Claude Pro's usage reset cycle. It is not guaranteed to match Anthropic's server-side accounting.

### Cost estimation

When a record has no `cost_usd` field (or the value is 0), cost is estimated via `estimate_cost()` using hardcoded per-million-token rates:

| Model match | Input | Output | Cache read | Cache write |
|---|---|---|---|---|
| `claude-opus` | $15.00 | $75.00 | $1.50 | $3.75 |
| `claude-sonnet` | $3.00 | $15.00 | $0.30 | $3.75 |
| `claude-haiku` | $0.25 | $1.25 | $0.03 | $0.30 |
| (fallback) | $3.00 | $15.00 | $0.30 | $3.75 |

These rates are approximations. Claude Code subscribers on Pro or Max plans pay a flat subscription — these figures are not actual billing amounts.

---

## Menu Bar App

### rumps

`rumps` is a high-level Python wrapper around `AppKit`/`NSStatusBar`. The app subclasses `rumps.App` and builds a static menu in `__init__`. Items are referenced by their title string (`self.menu["Item Title"]`).

`rumps.Timer` drives the 5-minute auto-refresh cycle.

### Menu colors (`_paint`)

macOS colors menu items using `NSAttributedString`. The `_paint(item, rgb)` function:

1. Constructs an `NSColor` from (R, G, B) 0–1 floats
2. Builds an `NSAttributedString` with that color and `NSFont.menuFontOfSize_`
3. Calls `item._menuitem.setAttributedTitle_(astr)`

**Critical invariant:** setting `item.title = "..."` in Python clears the attributed string. Therefore `_paint()` must be called after every title update in `refresh_data()`. Forgetting this causes items to revert to plain white text.

**Disabled vs. non-interactive items:** `rumps.MenuItem(callback=None)` is grayed out by macOS. Stat items (Session, Today, etc.) use `callback=lambda _: None` so they remain enabled and colorable while still doing nothing when clicked.

### Gauge percentage

There is no local API to query a user's Claude Pro session limit. The gauge shows:

```
gauge_pct = session_tokens / max_daily_tokens * 100
```

where `max_daily_tokens` is the peak daily total from the past 7 days. At gauge_pct < 40 the bar is gold, 40–75 is bright gold, ≥75 is orange-red.

---

## HTML Dashboard

### Template substitution

`HTML_TEMPLATE` is a raw string containing CSS blocks with `{ }` that would break Python's `str.format()`. All substitutions use a `dict` of `{placeholder}` → value strings and a loop calling `str.replace()`:

```python
for placeholder, value in substitutions.items():
    html = html.replace(placeholder, value)
```

**Never switch this to `.format()`.** The CSS variables (`--sand-dark: #0a0804;`) contain braces that `.format()` would try to parse as format fields and raise a `KeyError`.

### Output path

The HTML file is always written to:

```
/tmp/claude_spice_harvester.html   (macOS tempdir)
```

It is overwritten on every `refresh_data()` call and opened via `webbrowser.open("file://...")`.

---

## Themes

Each theme is a dict in the `THEMES` constant with these keys:

| Key | Type | Purpose |
|---|---|---|
| `name` | str | Display name in the Themes submenu |
| `menu_colors` | dict | Per-item `(R, G, B)` tuples for `_paint()` |
| `css_vars` | dict | CSS custom property name → value for the dashboard |
| `bg_gradients` | list[str] | CSS gradient strings for the layered background |
| `particles` | list[str] | Hex colors for the drifting particle JS |
| `title` | str | Dashboard `<h1>` and menu header |
| `tagline` | str | Dashboard subtitle |
| `ornament` | str | Decorative header string |
| `dividers` | list[str] | 7-element list of section divider labels |
| `footer` | str | Dashboard footer quote |
| `gauge_label` | str | Label above the session gauge |
| `stat_labels` | dict | Labels for the today / week / total stat cards |

To add a new theme, add an entry to `THEMES` and it automatically appears in the Themes submenu.

---

## Screenshot Mode

The app has a hidden `--screenshot` mode used to generate the screenshots in `screenshots/`:

```bash
python3 claude_spice_harvester.py --screenshot output.png
```

This requires `pyobjc`. It:
1. Launches the app normally
2. After 2 seconds, opens the menu bar menu programmatically
3. Captures a `330×360` region aligned to the status bar button
4. Quits

The capture uses macOS `screencapture -R x,y,w,h`. The region is computed dynamically from the `NSStatusBarWindow` frame.

---

## Considerations and Gotchas

**Template substitution must stay as `str.replace()`.**  
The HTML template contains CSS `{ }` blocks. Using `.format()` will break on them.

**`_paint()` must follow every title update.**  
Setting `.title` on a `rumps.MenuItem` clears `NSAttributedString`. The color must be re-applied each time.

**Session window is an approximation.**  
The 5-hour UTC boundary heuristic does not reflect Anthropic's actual internal session accounting. Users on Claude Pro may see discrepancies.

**Cost figures are estimates, not billing.**  
Claude Code subscribers pay a flat subscription. The per-token rates in `estimate_cost()` are approximations based on API pricing and will drift from reality as Anthropic changes prices.

**Local data only.**  
The app cannot see usage from other devices, the Claude web app, or the mobile app. It only reads from the local machine's `~/.claude/` directory.

**No public usage API for individual accounts.**  
Anthropic's Usage & Cost Admin API requires an organization account. There is no programmatic way to get the authoritative usage data shown at claude.ai/settings for a personal Pro or Max subscription.

**`pyobjc` is optional but expected.**  
On a fresh Python install without `pyobjc`, the app runs but all menu items are uncolored. Gated behind `_HAS_APPKIT` and `_HAS_OBJC` booleans.

**PyInstaller bundles and font loading.**  
The HTML dashboard loads Google Fonts at runtime via `@import url(...)`. When running as a standalone `.app` with no internet, fonts fall back to the system monospace font — the dashboard is still readable but loses the Cinzel/Share Tech Mono aesthetic.

---

## Extending the App

### Adding a new data field

1. Extract the field in `extract_usage_from_entries()` and include it in the returned record dict.
2. Accumulate it in `aggregate_records()` alongside the existing token fields.
3. Reference it in `build_html()` via the `substitutions` dict and add a corresponding placeholder in `HTML_TEMPLATE`.

### Adding a new theme

Add a new key to `THEMES` following the structure documented above. The Themes submenu is built dynamically from `THEMES.keys()`, so no other code changes are required.

### Changing the refresh interval

The timer is created in `ClaudeSpiceHarvesterApp.__init__`:

```python
self._timer = rumps.Timer(self._auto_refresh, 300)
```

Change `300` (seconds) to any value.
