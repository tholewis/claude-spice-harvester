#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════╗
║          {title} — Claude Code Usage             ║
║          "The spice must flow."                      ║
╚══════════════════════════════════════════════════════╝
A Dune-inspired macOS menu bar app that tracks your
Claude Code token usage from ~/.claude/

Requirements:
    pip install rumps
"""

import rumps
import json
import os
import glob
import tempfile
import webbrowser
from pathlib import Path
from datetime import datetime, date, timedelta, timezone as _tz

try:
    import AppKit as _AppKit
    _HAS_APPKIT = True
except ImportError:
    _HAS_APPKIT = False


# ─── Data Layer ──────────────────────────────────────────────────────────────

def get_claude_dir():
    return Path.home() / ".claude"


def get_appsupport_claude_dir():
    return Path.home() / "Library" / "Application Support" / "Claude"


def parse_jsonl_file(filepath):
    entries = []
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except (IOError, OSError):
        pass
    return entries


def extract_usage_from_entries(entries):
    records = []
    for entry in entries:
        usage = None
        model = "unknown"
        timestamp = None

        if entry.get("type") == "assistant":
            msg = entry.get("message", {})
            usage = msg.get("usage")
            model = msg.get("model", "unknown")
            timestamp = entry.get("timestamp")

        elif entry.get("role") == "assistant":
            usage = entry.get("usage")
            model = entry.get("model", "unknown")
            timestamp = entry.get("timestamp") or entry.get("created_at")

        if usage is None and "costUSD" in entry:
            records.append({
                "input_tokens": entry.get("inputTokens", 0),
                "output_tokens": entry.get("outputTokens", 0),
                "cache_read_tokens": entry.get("cacheReadTokens", 0),
                "cache_write_tokens": entry.get("cacheWriteTokens", 0),
                "cost_usd": entry.get("costUSD", 0.0),
                "model": entry.get("model", "unknown"),
                "timestamp": entry.get("timestamp"),
            })
            continue

        if usage:
            records.append({
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
                "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
                "cost_usd": usage.get("cost", 0.0),
                "model": model,
                "timestamp": timestamp,
            })

    return records


def estimate_cost(input_tokens, output_tokens, cache_read, cache_write, model):
    model = (model or "").lower()
    pricing = {
        "claude-opus": (15.0, 75.0, 1.50, 3.75),
        "claude-sonnet": (3.0, 15.0, 0.30, 3.75),
        "claude-haiku": (0.25, 1.25, 0.03, 0.30),
    }
    rates = (3.0, 15.0, 0.30, 3.75)
    for key, val in pricing.items():
        if key in model:
            rates = val
            break
    inp_rate, out_rate, cr_rate, cw_rate = rates
    return (
        input_tokens * inp_rate / 1_000_000
        + output_tokens * out_rate / 1_000_000
        + cache_read * cr_rate / 1_000_000
        + cache_write * cw_rate / 1_000_000
    )


def parse_datetime_utc(ts):
    """Parse ISO timestamp string to naive UTC datetime."""
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts, tz=_tz.utc).replace(tzinfo=None)
        s = str(ts).strip().rstrip("Z")
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ]:
            try:
                return datetime.strptime(s[:26], fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def parse_timestamp(ts):
    """Parse timestamp to local date."""
    if not ts:
        return None
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).date()
        ts_str = str(ts)
        for fmt in [
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]:
            try:
                return datetime.strptime(ts_str[:26], fmt).date()
            except ValueError:
                continue
    except Exception:
        pass
    return None


def get_session_window():
    """Current 5-hour UTC window — approximates Claude Pro session cycle."""
    now = datetime.now(_tz.utc).replace(tzinfo=None)
    window_hour = (now.hour // 5) * 5
    start = now.replace(hour=window_hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=5)
    reset_in = max(0.0, (end - now).total_seconds())
    return start, end, reset_in


def load_all_usage():
    claude_dir = get_claude_dir()
    appsupport_dir = get_appsupport_claude_dir()
    all_records = []
    files_found = 0

    patterns = [
        str(claude_dir / "projects" / "**" / "*.jsonl"),
        str(claude_dir / "sessions" / "**" / "*.jsonl"),
        str(claude_dir / "conversations" / "**" / "*.jsonl"),
        str(claude_dir / "**" / "*.jsonl"),
    ]
    if appsupport_dir.exists():
        patterns.append(str(appsupport_dir / "**" / "*.jsonl"))

    seen = set()
    for pattern in patterns:
        for fpath in glob.glob(pattern, recursive=True):
            if fpath not in seen:
                seen.add(fpath)
                files_found += 1
                records = extract_usage_from_entries(parse_jsonl_file(fpath))
                for r in records:
                    r["_file"] = fpath
                all_records.extend(records)

    for upath in [claude_dir / "usage.json", appsupport_dir / "usage.json"]:
        if upath.exists():
            try:
                with open(upath) as f:
                    data = json.load(f)
                if isinstance(data, list):
                    all_records.extend(data)
                elif isinstance(data, dict) and "records" in data:
                    all_records.extend(data["records"])
            except Exception:
                pass

    return aggregate_records(all_records, files_found)


def aggregate_records(records, files_found):
    today = date.today()
    seven_days_ago = today - timedelta(days=6)
    win_start, win_end, reset_in = get_session_window()

    zero = {"input_tokens": 0, "output_tokens": 0,
            "cache_read_tokens": 0, "cache_write_tokens": 0, "cost_usd": 0.0}

    totals = dict(zero)
    today_totals = dict(zero)
    week_totals = dict(zero)
    session_totals = dict(zero)
    per_day = {}
    per_model = {}

    for r in records:
        it = r.get("input_tokens", 0) or 0
        ot = r.get("output_tokens", 0) or 0
        cr = r.get("cache_read_tokens", 0) or 0
        cw = r.get("cache_write_tokens", 0) or 0
        model = r.get("model", "unknown") or "unknown"
        cost = r.get("cost_usd") or 0.0
        if cost == 0.0:
            cost = estimate_cost(it, ot, cr, cw, model)

        def add(d, _it=it, _ot=ot, _cr=cr, _cw=cw, _c=cost):
            d["input_tokens"] += _it
            d["output_tokens"] += _ot
            d["cache_read_tokens"] += _cr
            d["cache_write_tokens"] += _cw
            d["cost_usd"] += _c

        add(totals)
        if model not in per_model:
            per_model[model] = dict(zero)
        add(per_model[model])

        ts_date = parse_timestamp(r.get("timestamp"))
        if ts_date:
            key = str(ts_date)
            if key not in per_day:
                per_day[key] = dict(zero)
            add(per_day[key])
            if ts_date == today:
                add(today_totals)
            if ts_date >= seven_days_ago:
                add(week_totals)

        ts_dt = parse_datetime_utc(r.get("timestamp"))
        if ts_dt and win_start <= ts_dt < win_end:
            add(session_totals)

    daily_list = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        key = str(d)
        daily_list.append({"date": key, **per_day.get(key, dict(zero))})

    return {
        "totals": totals,
        "today": today_totals,
        "week": week_totals,
        "session": session_totals,
        "session_reset_in": reset_in,
        "daily": daily_list,
        "per_model": per_model,
        "files_scanned": files_found,
        "records_found": len(records),
        "last_updated": datetime.now().strftime("%H:%M:%S"),
    }


def fmt_tokens(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def fmt_reset(seconds):
    if seconds <= 0:
        return "resetting"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


# ─── HTML Dashboard ───────────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Claude Spice Harvester — Claude Code Usage</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;900&family=Cinzel+Decorative:wght@400;700&family=Share+Tech+Mono&display=swap');

  :root {
    {css_vars}
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--sand-dark);
    color: var(--text-main);
    font-family: 'Share Tech Mono', monospace;
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Layered dune background */
  .dune-bg {
    position: fixed; inset: 0; z-index: 0; pointer-events: none;
    background: {bg_gradients};
  }

  /* Subtle scan lines */
  .scanlines {
    position: fixed; inset: 0; z-index: 1; pointer-events: none;
    background: repeating-linear-gradient(
      0deg, transparent, transparent 3px,
      rgba(0,0,0,0.06) 3px, rgba(0,0,0,0.06) 4px
    );
  }

  /* Slow drifting sand particles */
  @keyframes drift {
    0%   { transform: translateX(-20px) translateY(0px);   opacity: 0; }
    20%  { opacity: 0.4; }
    80%  { opacity: 0.2; }
    100% { transform: translateX(120px) translateY(-30px); opacity: 0; }
  }

  .particle {
    position: fixed; width: 2px; height: 2px;
    background: var(--gold-mid); border-radius: 50%;
    animation: drift linear infinite;
    pointer-events: none; z-index: 2;
  }

  .container { max-width: 960px; margin: 0 auto; padding: 2.5rem 1.5rem; position: relative; z-index: 3; }

  /* ── Header ── */
  .header { text-align: center; margin-bottom: 2.5rem; }
  .ornament { color: var(--gold-deep); font-size: 0.75rem; letter-spacing: 0.6em; margin-bottom: 0.6rem; }
  h1 {
    font-family: 'Cinzel Decorative', serif;
    font-size: 2.8rem; font-weight: 700;
    background: linear-gradient(135deg, var(--gold-deep), var(--gold-glow), var(--gold-mid));
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
    letter-spacing: 0.08em;
  }
  .tagline {
    font-family: 'Cinzel', serif;
    color: var(--text-dim); font-size: 0.72rem;
    letter-spacing: 0.35em; margin-top: 0.4rem; text-transform: uppercase;
  }
  .updated { font-size: 0.65rem; color: var(--text-faint); margin-top: 0.7rem; letter-spacing: 0.15em; }

  /* ── Section divider ── */
  .divider {
    display: flex; align-items: center; gap: 0.8rem; margin: 2rem 0;
    color: var(--gold-deep);
  }
  .divider::before, .divider::after {
    content: ''; flex: 1; height: 1px;
    background: linear-gradient(90deg, transparent, var(--gold-deep));
  }
  .divider::after { background: linear-gradient(90deg, var(--gold-deep), transparent); }
  .divider span { font-family: 'Cinzel', serif; font-size: 0.62rem; letter-spacing: 0.3em; white-space: nowrap; }

  /* ── Session Panel ── */
  .session-panel {
    display: grid;
    grid-template-columns: 260px 1fr;
    gap: 1.5rem;
    background: var(--sand-mid);
    border: 1px solid var(--border);
    border-top: 2px solid var(--gold-mid);
    padding: 2rem;
    margin-bottom: 1.5rem;
    position: relative;
    overflow: hidden;
  }
  .session-panel::before {
    content: '';
    position: absolute; inset: 0;
    background: radial-gradient(ellipse at top left, var(--panel-glow), transparent 60%);
    pointer-events: none;
  }

  /* SVG gauge */
  .gauge-wrap { display: flex; align-items: center; justify-content: center; }
  .gauge-label { font-family: 'Cinzel', serif; font-size: 0.6rem; letter-spacing: 0.3em; color: var(--gold-mid); text-transform: uppercase; margin-bottom: 1.2rem; }

  /* Session right-side stats */
  .session-stats { display: flex; flex-direction: column; justify-content: center; gap: 1rem; padding-left: 1rem; }
  .session-stat-label { font-family: 'Cinzel', serif; font-size: 0.58rem; letter-spacing: 0.25em; color: var(--text-dim); text-transform: uppercase; margin-bottom: 0.2rem; }
  .session-stat-val { font-size: 2.2rem; font-weight: 700; color: var(--gold-bright); line-height: 1; }
  .session-stat-val.dim { font-size: 1.3rem; color: var(--text-main); }
  .session-stat-val.orange { color: var(--spice-orange); }
  .session-reset { display: flex; align-items: center; gap: 0.5rem; margin-top: 0.5rem; }
  .reset-badge {
    display: inline-flex; align-items: center; gap: 0.4rem;
    background: rgba(139,58,26,0.25); border: 1px solid var(--spice-red);
    padding: 0.3rem 0.7rem; font-size: 0.75rem; color: var(--spice-orange);
  }
  .reset-badge::before { content: '⟳'; font-size: 0.9rem; }
  .session-note { font-size: 0.62rem; color: var(--text-faint); margin-top: 0.8rem; line-height: 1.5; }
  .session-primary { display: flex; flex-direction: column; justify-content: center; }
  .session-big-num { font-size: 3rem; font-weight: 700; line-height: 1; margin: 0.4rem 0 0.2rem; }
  .session-pct-bar-wrap { height: 10px; background: var(--sand-pale); margin: 0.7rem 0 0.3rem; }
  .session-pct-bar-fill { height: 100%; }
  .session-pct-label { font-family: 'Cinzel', serif; font-size: 0.68rem; letter-spacing: 0.2em; margin-top: 0.2rem; }

  /* ── Stats grid ── */
  .stats-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin-bottom: 1.5rem; }
  .stat-card {
    background: var(--sand-mid);
    border: 1px solid var(--border);
    border-top: 2px solid var(--gold-deep);
    padding: 1.2rem 1rem;
    text-align: center;
    position: relative; overflow: hidden;
  }
  .stat-card::before {
    content: ''; position: absolute; inset: 0;
    background: radial-gradient(ellipse at top, var(--panel-glow), transparent 70%);
    pointer-events: none;
  }
  .stat-label { font-family: 'Cinzel', serif; font-size: 0.58rem; letter-spacing: 0.25em; color: var(--text-dim); text-transform: uppercase; margin-bottom: 0.5rem; }
  .stat-value { font-size: 1.8rem; font-weight: 700; color: var(--gold-bright); line-height: 1; }
  .stat-value.cost { color: var(--spice-orange); }
  .stat-sub { font-size: 0.62rem; color: var(--text-faint); margin-top: 0.3rem; }

  /* ── Breakdown card ── */
  .breakdown-card {
    background: var(--sand-mid); border: 1px solid var(--border);
    padding: 1.4rem; margin-bottom: 1rem;
  }
  .card-title {
    font-family: 'Cinzel', serif; font-size: 0.65rem;
    letter-spacing: 0.3em; color: var(--gold-mid);
    text-transform: uppercase; margin-bottom: 1.1rem;
  }
  .breakdown-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 0.4rem 0; border-bottom: 1px solid var(--text-faint);
    font-size: 0.82rem;
  }
  .breakdown-row:last-child { border-bottom: none; }
  .bk { color: var(--text-dim); }
  .bv { color: var(--text-main); font-weight: 600; }
  .bv.hi { color: var(--gold-bright); }
  .bv.co { color: var(--spice-orange); }

  /* ── Bar chart ── */
  .chart-card { background: var(--sand-mid); border: 1px solid var(--border); padding: 1.4rem; margin-bottom: 1rem; }
  .bars { display: flex; align-items: flex-end; gap: 0.4rem; height: 110px; }
  .bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 0.35rem; }
  .bar-fill {
    width: 100%;
    background: linear-gradient(180deg, var(--gold-bright), var(--gold-deep));
    min-height: 2px; position: relative;
  }
  .bar-fill.today { background: linear-gradient(180deg, var(--spice-bright), var(--spice-red)); }
  .bar-fill.today::after {
    content: ''; position: absolute; inset: 0;
    background: inherit; filter: blur(6px); opacity: 0.4; z-index: -1;
  }
  .bar-label { font-size: 0.58rem; color: var(--text-faint); }
  .bar-val { font-size: 0.6rem; color: var(--text-dim); }

  /* ── Model rows ── */
  .model-row {
    display: flex; align-items: center; gap: 1rem;
    padding: 0.45rem 0; border-bottom: 1px solid var(--text-faint); font-size: 0.78rem;
  }
  .model-row:last-child { border-bottom: none; }
  .model-name { flex: 0 0 200px; color: var(--text-dim); font-size: 0.72rem; }
  .model-bar-wrap { flex: 1; height: 5px; background: var(--sand-pale); }
  .model-bar { height: 100%; background: var(--gold-mid); }
  .model-tokens { flex: 0 0 70px; text-align: right; color: var(--text-main); }

  /* ── Footer ── */
  .footer {
    text-align: center; margin-top: 2.5rem;
    padding-top: 1.2rem; border-top: 1px solid var(--text-faint);
    font-size: 0.62rem; color: var(--text-faint);
    letter-spacing: 0.15em; font-family: 'Cinzel', serif;
    line-height: 1.8;
  }

  @media (max-width: 640px) {
    .session-panel { grid-template-columns: 1fr; }
    .stats-grid { grid-template-columns: 1fr; }
    h1 { font-size: 1.8rem; }
  }
</style>
</head>
<body>
<div class="dune-bg"></div>
<div class="scanlines"></div>

<!-- Drifting particles -->
<script>
(function() {
  var colors = {particles};
  for (var i = 0; i < 18; i++) {
    var p = document.createElement('div');
    p.className = 'particle';
    p.style.left  = Math.random() * 100 + 'vw';
    p.style.top   = Math.random() * 100 + 'vh';
    p.style.animationDuration = (20 + Math.random() * 40) + 's';
    p.style.animationDelay   = -(Math.random() * 40) + 's';
    p.style.background = colors[Math.floor(Math.random() * colors.length)];
    p.style.opacity = Math.random() * 0.5;
    document.body.appendChild(p);
  }
})();
</script>

<div class="container">

  <!-- Header -->
  <div class="header">
    <div class="ornament">{ornament}</div>
    <h1>{title}</h1>
    <div class="tagline">{tagline}</div>
    <div class="updated">Harvester reading as of {last_updated}</div>
  </div>

  <!-- Session window -->
  <div class="divider"><span>{session_divider}</span></div>

  <div class="session-panel">
    <div class="session-primary">
      <div class="session-stat-label">{gauge_label}</div>
      <div class="session-big-num" style="color:{val_color}">{session_tok_str}</div>
      <div style="font-size:0.62rem;letter-spacing:3px;color:#4a3d28;margin-bottom:0.4rem;">TOKENS THIS SESSION</div>
      <div class="session-pct-bar-wrap">
        <div class="session-pct-bar-fill" style="width:{gauge_pct_num}%;background:linear-gradient(90deg,{arc_color_start},{arc_color_end});"></div>
      </div>
      <div class="session-pct-label" style="color:{pct_color}">{gauge_pct_str}</div>
    </div>

    <div class="session-stats">
      <div>
        <div class="session-stat-label">Session input</div>
        <div class="session-stat-val dim">{session_input}</div>
      </div>
      <div>
        <div class="session-stat-label">Session output</div>
        <div class="session-stat-val dim">{session_output}</div>
      </div>
      <div>
        <div class="session-stat-label">Session cost</div>
        <div class="session-stat-val orange">${session_cost}</div>
      </div>
      <div class="session-reset">
        <span class="reset-badge">{reset_str}</span>
      </div>
      <div class="session-note">
        ⬡ Gauge scaled to peak daily usage (past 7 days).<br>
        ⬡ Session window = 5-hour UTC cycle (approx. Claude Pro).
      </div>
    </div>
  </div>

  <!-- All-time + today -->
  <div class="divider"><span>{reserves_divider}</span></div>

  <div class="stats-grid">
    <div class="stat-card">
      <div class="stat-label">{today_label}</div>
      <div class="stat-value">{today_tokens}</div>
      <div class="stat-sub">${today_cost} spent today</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{week_label}</div>
      <div class="stat-value">{week_tokens}</div>
      <div class="stat-sub">${week_cost} this week</div>
    </div>
    <div class="stat-card">
      <div class="stat-label">{total_label}</div>
      <div class="stat-value cost">${total_cost}</div>
      <div class="stat-sub">{total_tokens} tokens lifetime</div>
    </div>
  </div>

  <!-- Lifetime breakdown -->
  <div class="breakdown-card">
    <div class="card-title">{breakdown_title}</div>
    <div class="breakdown-row">
      <span class="bk">Input tokens</span><span class="bv hi">{total_input}</span>
    </div>
    <div class="breakdown-row">
      <span class="bk">Output tokens</span><span class="bv hi">{total_output}</span>
    </div>
    <div class="breakdown-row">
      <span class="bk">Cache read tokens</span><span class="bv">{total_cache_read}</span>
    </div>
    <div class="breakdown-row">
      <span class="bk">Cache write tokens</span><span class="bv">{total_cache_write}</span>
    </div>
    <div class="breakdown-row">
      <span class="bk">Estimated total cost</span><span class="bv co">${total_cost_full}</span>
    </div>
  </div>

  <!-- 7-day chart -->
  <div class="divider"><span>{chart_divider}</span></div>
  <div class="chart-card">
    <div class="card-title">{chart_title}</div>
    <div class="bars">
      {bar_html}
    </div>
  </div>

  {model_section}

  <div class="footer">
    {footer}<br>
    {files_scanned} SESSION FILES · {records_found} USAGE RECORDS · DATA SOURCE: ~/.claude/
  </div>

</div>
</body>
</html>"""


def build_html(data, theme):
    totals  = data["totals"]
    today   = data["today"]
    week    = data["week"]
    session = data["session"]
    daily   = data["daily"]
    per_model = data["per_model"]
    reset_in  = data["session_reset_in"]

    total_all   = totals["input_tokens"] + totals["output_tokens"]
    today_all   = today["input_tokens"] + today["output_tokens"]
    week_all    = week["input_tokens"] + week["output_tokens"]
    session_all = session["input_tokens"] + session["output_tokens"]

    # Session gauge — scale to max daily (past 7 days)
    max_daily = max((d["input_tokens"] + d["output_tokens"] for d in daily), default=1) or 1
    gauge_pct = min(100, int(session_all / max_daily * 100)) if max_daily else 0

    if gauge_pct < 40:
        arc_color_start, arc_color_end = "#8b6914", "#c9942a"
        pct_color = "#7a6345"
        val_color = "#c9942a"
    elif gauge_pct < 75:
        arc_color_start, arc_color_end = "#c9942a", "#e8b84b"
        pct_color = "#c9942a"
        val_color = "#e8b84b"
    else:
        arc_color_start, arc_color_end = "#c4581e", "#e06020"
        pct_color = "#c4581e"
        val_color = "#e06020"

    gauge_pct_str = f"{'▲ ' if gauge_pct >= 75 else ''}{gauge_pct}% OF PEAK DAY"

    # Bar chart
    today_str = str(date.today())
    bar_parts = []
    for d in daily:
        dtotal = d["input_tokens"] + d["output_tokens"]
        pct = max(2, int(dtotal / max_daily * 110)) if max_daily else 2
        is_today = d["date"] == today_str
        day_label = datetime.strptime(d["date"], "%Y-%m-%d").strftime("%a")
        cls = "bar-fill today" if is_today else "bar-fill"
        bar_parts.append(
            f'<div class="bar-col">'
            f'<div class="bar-val">{fmt_tokens(dtotal) if dtotal else ""}</div>'
            f'<div class="{cls}" style="height:{pct}px"></div>'
            f'<div class="bar-label">{day_label}</div>'
            f'</div>'
        )

    # Model section
    model_section = ""
    if per_model:
        model_total = sum(v["input_tokens"] + v["output_tokens"] for v in per_model.values()) or 1
        rows = ""
        for name, mv in sorted(per_model.items(),
                               key=lambda x: x[1]["input_tokens"] + x[1]["output_tokens"],
                               reverse=True):
            mt = mv["input_tokens"] + mv["output_tokens"]
            pct = int(mt / model_total * 100)
            short = name.replace("claude-", "").replace("-20", " '")
            rows += (
                f'<div class="model-row">'
                f'<span class="model-name">{short}</span>'
                f'<div class="model-bar-wrap"><div class="model-bar" style="width:{pct}%"></div></div>'
                f'<span class="model-tokens">{fmt_tokens(mt)}</span>'
                f'</div>'
            )
        model_section = (
            '<div class="divider"><span>{models_divider}</span></div>'
            '<div class="breakdown-card">'
            '<div class="card-title">{models_title}</div>'
            + rows + '</div>'
        )

    substitutions = {
        "{css_vars}":         "\n    ".join(f"{k}: {v};" for k, v in theme["css_vars"].items()),
        "{bg_gradients}":     ",\n    ".join(theme["bg_gradients"]),
        "{particles}":        json.dumps(theme["particles"]),

        "{last_updated}":     data["last_updated"],
        "{title}":            theme["title"],
        "{tagline}":          theme["tagline"],
        "{ornament}":         theme["ornament"],
        "{gauge_label}":      theme.get("gauge_label", "⬡ Spice Flow Gauge"),
        "{today_label}":      theme.get("stat_labels", {}).get("today", "Today's Harvest"),
        "{week_label}":       theme.get("stat_labels", {}).get("week", "7-Day Total"),
        "{total_label}":      theme.get("stat_labels", {}).get("total", "All-Time Guild Debt"),
        "{session_tok_str}":  fmt_tokens(session_all),
        "{session_divider}":  theme["dividers"][0],
        "{reserves_divider}": theme["dividers"][1],
        "{breakdown_title}":  theme["dividers"][2],
        "{chart_divider}":    theme["dividers"][3],
        "{chart_title}":      theme["dividers"][4],
        "{models_divider}":   theme["dividers"][5],
        "{models_title}":     theme["dividers"][6],
        "{footer}":           theme["footer"],

        "{session_input}":    fmt_tokens(session["input_tokens"]),
        "{session_output}":   fmt_tokens(session["output_tokens"]),
        "{session_cost}":     f"{session['cost_usd']:.4f}",
        "{reset_str}":        fmt_reset(reset_in),
        "{arc_color_start}":  arc_color_start,
        "{arc_color_end}":    arc_color_end,
        "{val_color}":        val_color,
        "{pct_color}":        pct_color,
        "{gauge_pct_str}":    gauge_pct_str,
        "{gauge_pct_num}":    str(gauge_pct),
        "{today_tokens}":     fmt_tokens(today_all),
        "{today_cost}":       f"{today['cost_usd']:.2f}",
        "{week_tokens}":      fmt_tokens(week_all),
        "{week_cost}":        f"{week['cost_usd']:.2f}",
        "{total_cost}":       f"{totals['cost_usd']:.2f}",
        "{total_tokens}":     fmt_tokens(total_all),
        "{total_cost_full}":  f"{totals['cost_usd']:.4f}",
        "{total_input}":      fmt_tokens(totals["input_tokens"]),
        "{total_output}":     fmt_tokens(totals["output_tokens"]),
        "{total_cache_read}": fmt_tokens(totals["cache_read_tokens"]),
        "{total_cache_write}":fmt_tokens(totals["cache_write_tokens"]),
        "{bar_html}":         "\n      ".join(bar_parts),
        "{model_section}":    model_section,
        "{files_scanned}":    str(data["files_scanned"]),
        "{records_found}":    str(data["records_found"]),
    }
    html = HTML_TEMPLATE
    for placeholder, value in substitutions.items():
        html = html.replace(placeholder, value)
    return html


# ─── Menu Bar App ─────────────────────────────────────────────────────────────

def _make_bar(pct, width=10):
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


# Dune palette as (R, G, B) 0-1 floats
_C_GOLD    = (0.91, 0.72, 0.29)   # bright melange gold   — session
_C_SAND    = (0.83, 0.65, 0.38)   # warm parchment        — today
_C_AMBER   = (0.72, 0.54, 0.23)   # desert amber          — week
_C_SPICE   = (0.77, 0.35, 0.12)   # spice orange          — total
_C_ACTION  = (0.79, 0.58, 0.17)   # guild gold            — open/refresh
_C_DANGER  = (0.60, 0.22, 0.09)   # blood-spice red       — quit

# Theme definitions
THEMES = {
    "dune": {
        "name": "Dune",
        "menu_colors": {
            "session": _C_GOLD,
            "session_pct": _C_SAND,
            "session_reset": _C_AMBER,
            "today": _C_SAND,
            "week": _C_AMBER,
            "total": _C_SPICE,
            "action": _C_ACTION,
            "danger": _C_DANGER,
        },
        "css_vars": {
            "--sand-dark": "#0a0804",
            "--sand-mid": "#13100a",
            "--sand-warm": "#1e1508",
            "--sand-pale": "#2e2210",
            "--gold-deep": "#6b5010",
            "--gold-mid": "#c9942a",
            "--gold-bright": "#e8b84b",
            "--gold-glow": "#f5d07a",
            "--spice-red": "#8b3a1a",
            "--spice-orange": "#c4581e",
            "--spice-bright": "#e06020",
            "--text-main": "#e8d5a3",
            "--text-dim": "#7a6345",
            "--text-faint": "#3d3020",
            "--border": "#2e2210",
            "--panel-glow": "rgba(201,148,42,0.07)",
        },
        "bg_gradients": [
            "radial-gradient(ellipse 80% 40% at 50% 90%, rgba(139,90,20,0.12), transparent)",
            "radial-gradient(ellipse 60% 30% at 20% 70%, rgba(196,88,30,0.07), transparent)",
            "radial-gradient(ellipse 40% 60% at 80% 20%, rgba(139,58,26,0.05), transparent)",
        ],
        "particles": ['#c9942a','#e8b84b','#8b6914','#c4581e'],
        "title": "CLAUDE SPICE HARVESTER",
        "tagline": "The spice must flow.",
        "ornament": "⬡ &nbsp; ARRAKIS DATA TERMINAL &nbsp; ⬡",
        "dividers": ["⬡ CURRENT SESSION WINDOW ⬡", "⬡ SPICE RESERVES ⬡", "Flow Breakdown — Lifetime", "⬡ 7-DAY HARVESTING RECORD ⬡", "Daily Spice Yield", "⬡ ORACLE MODELS ⬡", "Tokens by Model"],
        "footer": "He who controls the spice controls the universe.",
        "gauge_label": "⬡ Spice Flow Gauge",
        "stat_labels": {
            "today": "Today's Harvest",
            "week": "7-Day Total",
            "total": "All-Time Guild Debt",
        },
    },
    "caladan": {
        "name": "Caladan",
        "menu_colors": {
            "session":       (0.20, 0.72, 0.95),   # bright ocean cyan
            "session_pct":   (0.30, 0.60, 0.85),   # mid ocean blue
            "session_reset": (0.05, 0.50, 0.70),   # deep sea teal
            "today":         (0.30, 0.60, 0.85),
            "week":          (0.05, 0.50, 0.70),
            "total":         (0.00, 0.38, 0.60),   # abyssal blue
            "action":        (0.20, 0.65, 0.90),
            "danger":        (0.75, 0.30, 0.30),
        },
        "css_vars": {
            "--sand-dark":    "#000d1a",
            "--sand-mid":     "#001830",
            "--sand-warm":    "#00233f",
            "--sand-pale":    "#002e52",
            "--gold-deep":    "#005588",
            "--gold-mid":     "#1ea8d8",
            "--gold-bright":  "#34c8f5",
            "--gold-glow":    "#80e8ff",
            "--spice-red":    "#2aa88a",
            "--spice-orange": "#3ec8a8",
            "--spice-bright": "#60eed0",
            "--text-main":    "#c8eeff",
            "--text-dim":     "#5a8fae",
            "--text-faint":   "#1e3d55",
            "--border":       "#002e52",
            "--panel-glow":   "rgba(30,168,216,0.08)",
        },
        "bg_gradients": [
            "radial-gradient(ellipse 100% 40% at 50% 100%, rgba(0,90,180,0.22), transparent)",
            "radial-gradient(ellipse 60% 30% at 15% 65%, rgba(0,160,220,0.09), transparent)",
            "radial-gradient(ellipse 40% 60% at 85% 20%, rgba(0,210,255,0.05), transparent)",
        ],
        "particles": ['#1ea8d8','#34c8f5','#005588','#3ec8a8'],
        "title": "ATREIDES SIGNAL LOG",
        "tagline": "Water and will — the Atreides way.",
        "ornament": "〰 &nbsp; CALADAN DATA TERMINAL &nbsp; 〰",
        "dividers": [
            "〰 CURRENT SESSION WINDOW 〰",
            "〰 WATER RESERVES 〰",
            "Flow Breakdown — Lifetime",
            "〰 7-DAY SIGNAL RECORD 〰",
            "Daily Signal Yield",
            "〰 ATREIDES MODELS 〰",
            "Tokens by Model",
        ],
        "footer": "The sea remembers all. House Atreides endures.",
        "gauge_label": "〰 Signal Flow Gauge",
        "stat_labels": {
            "today": "Today's Tide",
            "week": "7-Day Current",
            "total": "All-Time Depth",
        },
    },
    "giedi_prime": {
        "name": "Giedi Prime",
        "menu_colors": {
            "session":       (0.65, 0.65, 0.65),   # cold steel
            "session_pct":   (0.50, 0.50, 0.50),
            "session_reset": (0.40, 0.40, 0.40),
            "today":         (0.50, 0.50, 0.50),
            "week":          (0.40, 0.40, 0.40),
            "total":         (0.72, 0.18, 0.18),   # machine red
            "action":        (0.72, 0.20, 0.20),
            "danger":        (0.88, 0.10, 0.10),
        },
        "css_vars": {
            "--sand-dark":    "#0d0d0d",
            "--sand-mid":     "#1a1a1a",
            "--sand-warm":    "#252525",
            "--sand-pale":    "#333333",
            "--gold-deep":    "#444444",
            "--gold-mid":     "#888888",
            "--gold-bright":  "#aaaaaa",
            "--gold-glow":    "#c00000",
            "--spice-red":    "#8b1010",
            "--spice-orange": "#b82020",
            "--spice-bright": "#d83030",
            "--text-main":    "#c8c8c8",
            "--text-dim":     "#707070",
            "--text-faint":   "#404040",
            "--border":       "#333333",
            "--panel-glow":   "rgba(180,25,25,0.10)",
        },
        "bg_gradients": [
            "radial-gradient(ellipse 90% 35% at 50% 100%, rgba(160,20,20,0.18), transparent)",
            "radial-gradient(ellipse 50% 50% at 5%  50%, rgba(70,70,70,0.08),   transparent)",
            "radial-gradient(ellipse 40% 60% at 95% 10%, rgba(50,50,50,0.06),   transparent)",
        ],
        "particles": ['#888888','#aaaaaa','#444444','#b82020'],
        "title": "HARKONNEN PROCESSOR",
        "tagline": "Consume. Calculate. Conquer.",
        "ornament": "⬛ &nbsp; GIEDI PRIME INDUSTRIAL TERMINAL &nbsp; ⬛",
        "dividers": [
            "// CURRENT SESSION WINDOW //",
            "// PRODUCTION RESERVES //",
            "Processing Breakdown — Lifetime",
            "// 7-DAY YIELD RECORD //",
            "Daily Processing Output",
            "// HARKONNEN MODELS //",
            "Tokens by Model",
        ],
        "footer": "Efficiency is the only virtue. — Baron Harkonnen",
        "gauge_label": "⬛ Processing Load Gauge",
        "stat_labels": {
            "today": "Today's Output",
            "week": "7-Day Yield",
            "total": "All-Time Production",
        },
    },
}


def load_config():
    config_dir = Path.home() / "Library" / "Application Support" / "ClaudeSpiceHarvester"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    if config_file.exists():
        try:
            with open(config_file, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"theme": "dune"}


def save_config(config):
    config_dir = Path.home() / "Library" / "Application Support" / "ClaudeSpiceHarvester"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "config.json"
    try:
        with open(config_file, "w") as f:
            json.dump(config, f)
    except Exception:
        pass



def _paint(item, rgb, size=13.5):
    """Apply an NSAttributedString color to a rumps MenuItem."""
    if not _HAS_APPKIT:
        return
    r, g, b = rgb
    color = _AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, 1.0)
    font  = _AppKit.NSFont.menuFontOfSize_(size)
    attrs = {
        _AppKit.NSForegroundColorAttributeName: color,
        _AppKit.NSFontAttributeName: font,
    }
    astr = _AppKit.NSAttributedString.alloc().initWithString_attributes_(
        item._menuitem.title(), attrs
    )
    item._menuitem.setAttributedTitle_(astr)




class ClaudeSpiceHarvesterApp(rumps.App):
    def __init__(self):
        super().__init__(name="Claude Spice Harvester", title="🏜", quit_button=None)
        self._data = None
        self._html_path = os.path.join(tempfile.gettempdir(), "claude_spice_harvester.html")
        self._config = load_config()
        self._theme = THEMES.get(self._config.get("theme", "dune"), THEMES["dune"])


        _noop = lambda _: None  # noqa: E731  — keeps stat items enabled (not grayed out)
        self.menu = [
            rumps.MenuItem(f"⬡  {self._theme['title']}  ⬡"),
            None,
            rumps.MenuItem("Session",        callback=_noop),
            rumps.MenuItem("Session Pct",    callback=_noop),
            rumps.MenuItem("Session Reset",  callback=_noop),
            None,
            rumps.MenuItem("Today",          callback=_noop),
            rumps.MenuItem("This Week",      callback=_noop),
            rumps.MenuItem("All Time",       callback=_noop),
            None,
            rumps.MenuItem("Open Spice Ledger",         callback=self.open_dashboard),
            rumps.MenuItem("Refresh Harvester Reading", callback=self.refresh_data),
            None,
            self._create_theme_menu(),
            None,
            rumps.MenuItem("Leave Arrakis", callback=rumps.quit_application),
        ]
        self.menu[f"⬡  {self._theme['title']}  ⬡"].set_callback(None)
        # Gradient shimmer on the header title

        self.refresh_data(None)
        self._timer = rumps.Timer(self._auto_refresh, 300)
        self._timer.start()

    def _update_menu(self):
        # Find header menu item
        header_item = None
        for item in self.menu:
            if item.startswith("⬡ ") and item.endswith(" ⬡"):
                header_item = item
                break
        if header_item:
            new_title = f"⬡  {self._theme['title']}  ⬡"
            self.menu[header_item].title = new_title
        # Repaint actions
        _paint(self.menu["Open Spice Ledger"], self._theme["menu_colors"]["action"])
        _paint(self.menu["Refresh Harvester Reading"], self._theme["menu_colors"]["action"])
        _paint(self.menu["Leave Arrakis"], self._theme["menu_colors"]["danger"])


    def _create_theme_menu(self):
        theme_menu = rumps.MenuItem("Themes")
        for theme_key, theme_data in THEMES.items():
            item = rumps.MenuItem(theme_data["name"], callback=self._switch_theme)
            item.theme_key = theme_key
            if theme_key == self._config.get("theme", "dune"):
                item.state = True
            theme_menu.add(item)
        return theme_menu

    def _switch_theme(self, sender):
        theme_key = sender.theme_key
        self._config["theme"] = theme_key
        save_config(self._config)
        self._theme = THEMES[theme_key]
        self._update_menu()
        self.refresh_data(None)

    def _auto_refresh(self, _):
        self.refresh_data(None)

    @rumps.clicked("Refresh Harvester Reading")
    def refresh_data(self, _):
        self._data = load_all_usage()
        t       = self._data["totals"]
        td      = self._data["today"]
        sess    = self._data["session"]
        week    = self._data["week"]
        reset_in = self._data["session_reset_in"]

        total_tok   = t["input_tokens"]    + t["output_tokens"]
        today_tok   = td["input_tokens"]   + td["output_tokens"]
        week_tok    = week["input_tokens"] + week["output_tokens"]
        session_tok = sess["input_tokens"] + sess["output_tokens"]

        if total_tok > 0:
            self.title = f"🏜  {fmt_tokens(session_tok)} session  ·  {fmt_reset(reset_in)}"
        else:
            self.title = "🏜  No spice yet"

        daily     = self._data["daily"]
        max_daily = max((d["input_tokens"] + d["output_tokens"] for d in daily), default=1) or 1
        sess_pct  = min(100, int(session_tok / max_daily * 100))
        bar       = _make_bar(sess_pct, 8)

        self.menu["Session"].title = (
            f"◈  Session  {bar}  {fmt_tokens(session_tok)}"
        )
        self.menu["Session Pct"].title = (
            f"        {sess_pct}% of peak day"
        )
        self.menu["Session Reset"].title = (
            f"    Reset in  {fmt_reset(reset_in)}"
        )
        self.menu["Today"].title = (
            f"    Today    {fmt_tokens(today_tok)}"
        )
        self.menu["This Week"].title = (
            f"    This Week  {fmt_tokens(week_tok)}"
        )
        self.menu["All Time"].title = (
            f"    Total    {fmt_tokens(total_tok)} tokens  ·  ${t['cost_usd']:.2f}"
        )

        # Re-apply colors after title change (title change clears attributed string)
        _paint(self.menu["Session"],       self._theme["menu_colors"]["session"])
        _paint(self.menu["Session Pct"],   self._theme["menu_colors"]["session_pct"])
        _paint(self.menu["Session Reset"], self._theme["menu_colors"]["session_reset"])
        _paint(self.menu["Today"],         self._theme["menu_colors"]["today"])
        _paint(self.menu["This Week"],     self._theme["menu_colors"]["week"])
        _paint(self.menu["All Time"],      self._theme["menu_colors"]["total"])

        html = build_html(self._data, self._theme)
        with open(self._html_path, "w", encoding="utf-8") as f:
            f.write(html)

    @rumps.clicked("Open Spice Ledger")
    def open_dashboard(self, _):
        if self._data is None:
            self.refresh_data(None)
        webbrowser.open(f"file://{self._html_path}")


def main():
    ClaudeSpiceHarvesterApp().run()


if __name__ == "__main__":
    main()
