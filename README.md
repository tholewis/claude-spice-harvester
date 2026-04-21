# 🏜 Claude Spice Harvester
### *A Dune-inspired macOS menu bar app for Claude Code token usage*

> "The spice must flow." — Dune

---

## What it does

Claude Spice Harvester sits in your macOS menu bar and shows your Claude Code token usage at a glance. Click **Open Spice Ledger** for a full themed dashboard with session gauge, charts, and per-model breakdowns.

**Menu bar shows:**
- Session token count + time until reset
- Colored stats per time window (session · today · this week · all-time)

**Dashboard shows:**
- Session gauge (scaled to your peak daily usage)
- Today's and this week's token totals and cost
- 7-day bar chart ("Harvesting Record")
- Per-model token breakdown
- All-time totals and estimated cost

---

## Quick Start

```bash
# 1. Install the one dependency
pip3 install rumps

# 2. Run it
python3 spice_meter.py
```

`🏜` appears in your menu bar immediately. No account, no API key, no network calls — it reads directly from `~/.claude/`.

---

## Themes

Switch themes from the **Themes** submenu in the menu bar:

| Theme | Flavor |
|---|---|
| **Dune** | Arrakis — gold, amber, and spice red on deep desert black |
| **Caladan** | House Atreides — ocean blues and teals |
| **Giedi Prime** | House Harkonnen — industrial grays and machine red |

The selected theme persists between sessions.

---

## Build a standalone .app

```bash
chmod +x build_app.sh
./build_app.sh
```

Produces `SpiceMeter.app`. Drag to `/Applications` and double-click.

**First launch:** macOS Gatekeeper will warn about an unidentified developer. Fix it once:
> Right-click `SpiceMeter.app` → **Open** → **Open**

---

## How it reads your data

Spice Harvester scans `~/.claude/projects/**/*.jsonl` for Claude Code's JSONL session files and totals token usage locally. No data leaves your machine.

**Session window:** Claude Pro resets every 5 hours on UTC boundaries (0h, 5h, 10h, 15h, 20h). The app shows time until the next reset and scales the session gauge against your peak daily usage from the past 7 days.

---

## Customization

Edit `spice_meter.py` directly:

| What | Where |
|---|---|
| Refresh interval | `300` (seconds) in `SpiceMeterApp.__init__` |
| Token pricing | `pricing` dict in `estimate_cost()` |
| Menu bar icon | `"🏜"` in `SpiceMeterApp.__init__` |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| "No spice yet" | Claude Code hasn't been used yet, or `~/.claude/` doesn't exist |
| $0.00 cost | Cost is estimated from approximate model pricing; actual bills may differ |
| App won't open | Right-click → Open (Gatekeeper, one time only) |
| Menu bar text cut off | macOS quirk on smaller screens — normal behavior |

---

## Requirements

- macOS 12+
- Python 3.9+
- [`rumps`](https://github.com/jaredks/rumps) (`pip3 install rumps`)
- `pyobjc` for menu color support (usually pre-installed on macOS)

---

*Reads from `~/.claude/` · No network calls · Data stays local*  
*Built with `rumps` · Dune theme inspired by Frank Herbert*
