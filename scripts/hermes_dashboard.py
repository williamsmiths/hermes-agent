#!/usr/bin/env python3
"""Dashboard HTML tong hop trang thai Hermes (tieng Viet).

Gom 3 mang du lieu tu ~/.hermes:
  1. Skills  - tat ca (bundled + agent-created), doc frontmatter + telemetry .usage.json
  2. Sessions - liet ke phien chat theo project (cot cwd) tu state.db
  3. Memory  - SOUL.md + memories/USER.md + MEMORY.md

Cach dung:
    python scripts/hermes_dashboard.py            # tao + mo browser
    python scripts/hermes_dashboard.py --no-open  # khong mo browser
    python scripts/hermes_dashboard.py --out x.html
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import webbrowser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:
    yaml = None


def hermes_home() -> Path:
    env = os.getenv("HERMES_HOME")
    return Path(env) if env else Path.home() / ".hermes"


def esc(s) -> str:
    return html.escape(str(s))


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def ts_to_dt(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except Exception:
        return None


def humanize(dt) -> str:
    return dt.astimezone().strftime("%Y-%m-%d %H:%M") if dt else "—"


def read_frontmatter(skill_md: Path) -> dict:
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return {}
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}
    block = m.group(1)
    if yaml is not None:
        try:
            data = yaml.safe_load(block) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    out: dict = {}
    for line in block.splitlines():
        mm = re.match(r"^(title|description|name|version):\s*(.+)$", line)
        if mm:
            out[mm.group(1)] = mm.group(2).strip().strip('"')
    return out


# --------------------------------------------------------------------------
# 1. Skills
# --------------------------------------------------------------------------
def collect_skills() -> dict:
    home = hermes_home()
    skills_root = home / "skills"
    usage_path = skills_root / ".usage.json"
    usage = {}
    if usage_path.exists():
        try:
            usage = json.loads(usage_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            usage = {}

    by_category: dict[str, list] = defaultdict(list)
    agent_created = 0
    total = 0
    if skills_root.exists():
        for skill_md in sorted(skills_root.rglob("SKILL.md")):
            rel = skill_md.relative_to(skills_root)
            parts = rel.parts
            category = parts[0] if len(parts) > 1 else "(root)"
            name = skill_md.parent.name
            fm = read_frontmatter(skill_md)
            meta = usage.get(name, {})
            is_agent = meta.get("created_by") == "agent"
            agent_created += 1 if is_agent else 0
            total += 1
            by_category[category].append({
                "name": name,
                "title": (fm.get("title") or name),
                "description": str(fm.get("description") or "").strip(),
                "is_agent": is_agent,
                "use_count": meta.get("use_count", 0),
                "created": parse_dt(meta.get("created_at")),
                "pinned": bool(meta.get("pinned")),
            })
    return {"by_category": dict(sorted(by_category.items())),
            "total": total, "agent_created": agent_created}


# --------------------------------------------------------------------------
# 2. Sessions (theo project / cwd)
# --------------------------------------------------------------------------
def collect_sessions() -> dict:
    home = hermes_home()
    db_path = home / "state.db"
    if not db_path.exists():
        return {"by_project": {}, "total": 0, "tokens": 0}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, source, model, title, cwd, started_at, ended_at, "
        "message_count, input_tokens, output_tokens "
        "FROM sessions ORDER BY started_at DESC"
    ).fetchall()
    conn.close()

    by_project: dict[str, list] = defaultdict(list)
    total_tokens = 0
    for r in rows:
        cwd = r["cwd"] or "(không rõ thư mục)"
        project = Path(cwd).name if r["cwd"] else "(không rõ)"
        toks = (r["input_tokens"] or 0) + (r["output_tokens"] or 0)
        total_tokens += toks
        by_project[project].append({
            "id": r["id"],
            "source": r["source"],
            "model": r["model"] or "—",
            "title": r["title"] or "(chưa đặt tên)",
            "cwd": cwd,
            "started": ts_to_dt(r["started_at"]),
            "messages": r["message_count"] or 0,
            "tokens": toks,
        })
    return {"by_project": dict(by_project), "total": len(rows), "tokens": total_tokens}


# --------------------------------------------------------------------------
# 3. Memory
# --------------------------------------------------------------------------
def collect_memory() -> dict:
    home = hermes_home()
    out = {}
    for label, path in (
        ("SOUL.md (danh tính)", home / "SOUL.md"),
        ("USER.md (hồ sơ về bạn)", home / "memories" / "USER.md"),
        ("MEMORY.md (kiến thức)", home / "memories" / "MEMORY.md"),
    ):
        if path.exists():
            try:
                out[label] = path.read_text(encoding="utf-8", errors="replace").strip()
            except Exception:
                out[label] = "(không đọc được)"
    return out


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------
def render(skills: dict, sessions: dict, memory: dict) -> str:
    now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")

    # Skills section
    skill_blocks = []
    for category, items in skills["by_category"].items():
        chips = []
        for it in items:
            cls = "chip agent" if it["is_agent"] else "chip"
            star = "📌" if it["pinned"] else ("✨" if it["is_agent"] else "")
            tip = esc(it["description"]) or esc(it["title"])
            chips.append(f'<span class="{cls}" title="{tip}">{star}{esc(it["title"])}'
                         f'<small>·{it["use_count"]}</small></span>')
        skill_blocks.append(
            f'<div class="cat"><h4>{esc(category)} <em>({len(items)})</em></h4>'
            f'<div class="chips">{"".join(chips)}</div></div>'
        )

    # Sessions section
    sess_blocks = []
    for project, items in sessions["by_project"].items():
        rows_html = []
        for s in items:
            rows_html.append(
                f'<tr><td>{esc(s["title"])}</td><td><code>{esc(s["source"])}</code></td>'
                f'<td>{esc(s["model"])}</td><td>{s["messages"]}</td>'
                f'<td>{s["tokens"]:,}</td><td>{humanize(s["started"])}</td></tr>'
            )
        sess_blocks.append(
            f'<div class="proj"><h4>📁 {esc(project)} <em>({len(items)} phiên)</em></h4>'
            f'<table><thead><tr><th>Tiêu đề</th><th>Nguồn</th><th>Model</th>'
            f'<th>Tin nhắn</th><th>Token</th><th>Bắt đầu</th></tr></thead>'
            f'<tbody>{"".join(rows_html)}</tbody></table></div>'
        )
    if not sess_blocks:
        sess_blocks.append('<div class="empty">Chưa có phiên chat nào.</div>')

    # Memory section
    mem_blocks = []
    for label, content in memory.items():
        mem_blocks.append(
            f'<div class="memcard"><h4>{esc(label)}</h4>'
            f'<pre>{esc(content)}</pre></div>'
        )
    if not mem_blocks:
        mem_blocks.append('<div class="empty">Chưa có dữ liệu memory.</div>')

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes · Bảng điều khiển</title>
<style>
  :root {{ --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#e6edf3;
    --dim:#8b949e; --gold:#ffd700; --green:#3fb950; --blue:#58a6ff; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:var(--bg); color:var(--text); padding:32px; }}
  .wrap {{ max-width:1100px; margin:0 auto; }}
  h1 {{ margin:0 0 4px; font-size:26px; }} h1 .s {{ color:var(--gold); }}
  .sub {{ color:var(--dim); font-size:13px; margin-bottom:24px; }}
  .summary {{ display:flex; gap:16px; flex-wrap:wrap; margin-bottom:28px; }}
  .box {{ background:var(--panel); border:1px solid var(--border); border-radius:12px;
    padding:16px 22px; min-width:140px; }}
  .box .n {{ font-size:28px; font-weight:700; color:var(--gold); }}
  .box .l {{ color:var(--dim); font-size:13px; }}
  section {{ background:var(--panel); border:1px solid var(--border); border-radius:14px;
    padding:22px; margin-bottom:22px; }}
  section > h2 {{ margin:0 0 18px; font-size:19px; border-bottom:1px solid var(--border);
    padding-bottom:10px; }}
  .cat, .proj {{ margin-bottom:16px; }}
  .cat h4, .proj h4, .memcard h4 {{ margin:0 0 8px; font-size:15px; color:var(--blue); }}
  .cat h4 em, .proj h4 em {{ color:var(--dim); font-style:normal; font-size:12px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .chip {{ background:#21262d; border:1px solid var(--border); border-radius:16px;
    padding:4px 11px; font-size:12px; cursor:default; }}
  .chip.agent {{ border-color:var(--green); color:var(--green);
    background:rgba(63,185,80,.1); }}
  .chip small {{ color:var(--dim); margin-left:4px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ text-align:left; padding:7px 10px; border-bottom:1px solid var(--border); }}
  th {{ color:var(--dim); font-weight:600; }}
  td code {{ color:var(--blue); }}
  .memcard {{ margin-bottom:16px; }}
  .memcard pre {{ background:#0d1117; border:1px solid var(--border); border-radius:8px;
    padding:14px; white-space:pre-wrap; word-wrap:break-word; font-size:12.5px;
    line-height:1.55; color:var(--text); max-height:280px; overflow:auto; }}
  .empty {{ color:var(--dim); text-align:center; padding:30px; }}
  footer {{ text-align:center; color:var(--dim); font-size:12px; margin-top:24px; }}
</style></head>
<body><div class="wrap">
  <h1><span class="s">☤</span> Bảng điều khiển Hermes</h1>
  <div class="sub">Tạo lúc {esc(now_str)} · Nguồn: ~/.hermes</div>

  <div class="summary">
    <div class="box"><div class="n">{skills['total']}</div><div class="l">Tổng skill</div></div>
    <div class="box"><div class="n">{skills['agent_created']}</div><div class="l">Skill agent tự tạo</div></div>
    <div class="box"><div class="n">{sessions['total']}</div><div class="l">Phiên chat</div></div>
    <div class="box"><div class="n">{sessions['tokens']:,}</div><div class="l">Tổng token</div></div>
  </div>

  <section>
    <h2>🧠 Skills (✨ = agent tự tạo · số sau dấu · = lượt dùng)</h2>
    {"".join(skill_blocks)}
  </section>

  <section>
    <h2>💬 Phiên chat theo project</h2>
    {"".join(sess_blocks)}
  </section>

  <section>
    <h2>📝 Memory / Danh tính</h2>
    {"".join(mem_blocks)}
  </section>

  <footer>Hermes Agent · Bảng điều khiển cục bộ · dữ liệu chỉ nằm trên máy này</footer>
</div></body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Dashboard HTML tong hop trang thai Hermes")
    ap.add_argument("--no-open", action="store_true", help="Khong mo browser")
    ap.add_argument("--out", type=str, default="", help="Duong dan file HTML output")
    args = ap.parse_args()

    skills = collect_skills()
    sessions = collect_sessions()
    memory = collect_memory()
    out_html = render(skills, sessions, memory)

    out_path = Path(args.out) if args.out else (hermes_home() / "hermes_dashboard.html")
    out_path.write_text(out_html, encoding="utf-8")
    print(f"✅ Đã tạo dashboard: {out_path}")
    print(f"   Skills: {skills['total']} (agent: {skills['agent_created']}) · "
          f"Phiên: {sessions['total']} · Token: {sessions['tokens']:,}")
    if not args.no_open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    main()
