#!/usr/bin/env python3
"""Sinh báo cáo HTML các skill mà agent học/tạo/cập nhật trong N ngày qua.

Nguồn dữ liệu: ~/.hermes/skills/.usage.json  (telemetry chính thức của curator).
Chỉ track các skill có created_by="agent" (skill bundled/hub không nằm ở đây).

Cách dùng:
    python scripts/skills_weekly_report.py            # 7 ngày qua, mở trình duyệt
    python scripts/skills_weekly_report.py --days 30  # 30 ngày qua
    python scripts/skills_weekly_report.py --no-open  # không tự mở trình duyệt
    python scripts/skills_weekly_report.py --all      # mọi skill, bỏ lọc thời gian
"""
from __future__ import annotations

import argparse
import html
import os
import re
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


def hermes_home() -> Path:
    env = os.getenv("HERMES_HOME")
    if env:
        return Path(env)
    return Path.home() / ".hermes"


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def find_skill_md(skills_root: Path, name: str) -> Path | None:
    """Tìm SKILL.md theo tên skill (có thể nằm trong category con)."""
    direct = skills_root / name / "SKILL.md"
    if direct.exists():
        return direct
    for p in skills_root.rglob("SKILL.md"):
        if p.parent.name == name:
            return p
    return None


def read_frontmatter(skill_md: Path | None) -> dict:
    if not skill_md or not skill_md.exists():
        return {}
    text = skill_md.read_text(encoding="utf-8", errors="replace")
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
    # Fallback parser tối giản cho title/description trên 1 dòng
    out: dict = {}
    for line in block.splitlines():
        mm = re.match(r"^(title|description|name|version):\s*(.+)$", line)
        if mm:
            out[mm.group(1)] = mm.group(2).strip().strip('"')
    return out


def humanize(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M")


def relative(dt: datetime | None, now: datetime) -> str:
    if not dt:
        return ""
    delta = now - dt
    secs = int(delta.total_seconds())
    if secs < 3600:
        return f"{secs // 60} phút trước"
    if secs < 86400:
        return f"{secs // 3600} giờ trước"
    return f"{secs // 86400} ngày trước"


def collect(days: int | None) -> list[dict]:
    import json

    home = hermes_home()
    skills_root = home / "skills"
    usage_path = skills_root / ".usage.json"
    if not usage_path.exists():
        return []
    usage = json.loads(usage_path.read_text(encoding="utf-8") or "{}")

    now = datetime.now(timezone.utc)
    cutoff = None if days is None else now - timedelta(days=days)

    rows: list[dict] = []
    for name, meta in usage.items():
        created = parse_dt(meta.get("created_at"))
        patched = parse_dt(meta.get("last_patched_at"))
        used = parse_dt(meta.get("last_used_at"))
        viewed = parse_dt(meta.get("last_viewed_at"))
        # "hoạt động gần nhất" = max của mọi mốc thời gian
        activity = max([d for d in (created, patched, used, viewed) if d], default=None)

        if cutoff and activity and activity < cutoff:
            continue
        if cutoff and activity is None:
            continue

        fm = read_frontmatter(find_skill_md(skills_root, name))
        rows.append({
            "name": name,
            "title": (fm.get("title") or name).strip(),
            "description": str(fm.get("description") or "").strip(),
            "created": created,
            "patched": patched,
            "used": used,
            "state": meta.get("state", "active"),
            "pinned": bool(meta.get("pinned")),
            "use_count": meta.get("use_count", 0),
            "patch_count": meta.get("patch_count", 0),
            "view_count": meta.get("view_count", 0),
            "activity": activity,
            "rel": relative(activity, now),
        })

    rows.sort(key=lambda r: (r["activity"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return rows


def render_html(rows: list[dict], days: int | None) -> str:
    now_str = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    period = "toàn bộ thời gian" if days is None else f"{days} ngày qua"
    total = len(rows)
    new_count = sum(1 for r in rows if r["created"] and (days is None or True))
    total_uses = sum(r["use_count"] for r in rows)

    def esc(s: str) -> str:
        return html.escape(str(s))

    cards = []
    if not rows:
        cards.append('<div class="empty">Không có skill nào do agent tạo/cập nhật trong khoảng thời gian này.</div>')
    for r in rows:
        badges = []
        if r["created"] and (days is None or (datetime.now(timezone.utc) - r["created"]).days <= (days or 9999)):
            badges.append('<span class="badge new">MỚI TẠO</span>')
        if r["pinned"]:
            badges.append('<span class="badge pin">📌 PINNED</span>')
        badges.append(f'<span class="badge state state-{esc(r["state"])}">{esc(r["state"]).upper()}</span>')
        cards.append(f"""
        <div class="card">
          <div class="card-head">
            <h3>{esc(r['title'])}</h3>
            <div class="badges">{''.join(badges)}</div>
          </div>
          <code class="name">{esc(r['name'])}</code>
          <p class="desc">{esc(r['description']) or '<em>(không có mô tả)</em>'}</p>
          <div class="meta">
            <span title="Tạo lúc">🌱 {humanize(r['created'])}</span>
            <span title="Sửa lần cuối">✏️ {humanize(r['patched'])}</span>
            <span title="Dùng lần cuối">▶️ {humanize(r['used'])}</span>
          </div>
          <div class="stats">
            <span>Đã dùng <b>{r['use_count']}</b></span>
            <span>Sửa <b>{r['patch_count']}</b></span>
            <span>Xem <b>{r['view_count']}</b></span>
            <span class="rel">{esc(r['rel'])}</span>
          </div>
        </div>""")

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes · Skill đã học ({esc(period)})</title>
<style>
  :root {{
    --bg:#0d1117; --panel:#161b22; --border:#30363d; --text:#e6edf3;
    --dim:#8b949e; --gold:#ffd700; --green:#3fb950; --blue:#58a6ff; --pin:#d29922;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
         background:var(--bg); color:var(--text); padding:32px; }}
  .wrap {{ max-width:1000px; margin:0 auto; }}
  header h1 {{ margin:0 0 4px; font-size:26px; }}
  header h1 .star {{ color:var(--gold); }}
  header .sub {{ color:var(--dim); font-size:14px; }}
  .summary {{ display:flex; gap:16px; margin:24px 0; flex-wrap:wrap; }}
  .stat-box {{ background:var(--panel); border:1px solid var(--border); border-radius:12px;
             padding:16px 22px; min-width:130px; }}
  .stat-box .num {{ font-size:30px; font-weight:700; color:var(--gold); }}
  .stat-box .lbl {{ color:var(--dim); font-size:13px; margin-top:2px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(300px,1fr)); gap:16px; }}
  .card {{ background:var(--panel); border:1px solid var(--border); border-radius:12px; padding:18px;
          transition:.15s; }}
  .card:hover {{ border-color:var(--blue); transform:translateY(-2px); }}
  .card-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:8px; }}
  .card h3 {{ margin:0; font-size:17px; }}
  .name {{ color:var(--blue); font-size:12px; display:block; margin:6px 0 10px; }}
  .desc {{ color:var(--text); font-size:14px; line-height:1.5; margin:0 0 14px; opacity:.92; }}
  .badges {{ display:flex; flex-direction:column; gap:4px; align-items:flex-end; }}
  .badge {{ font-size:10px; font-weight:700; padding:2px 8px; border-radius:20px; white-space:nowrap; }}
  .badge.new {{ background:rgba(63,185,80,.15); color:var(--green); border:1px solid var(--green); }}
  .badge.pin {{ background:rgba(210,153,34,.15); color:var(--pin); }}
  .badge.state-active {{ background:rgba(88,166,255,.12); color:var(--blue); }}
  .badge.state-stale {{ background:rgba(139,148,158,.15); color:var(--dim); }}
  .badge.state-archived {{ background:rgba(248,81,73,.12); color:#f85149; }}
  .meta {{ display:flex; gap:14px; flex-wrap:wrap; color:var(--dim); font-size:12px; margin-bottom:10px; }}
  .stats {{ display:flex; gap:14px; flex-wrap:wrap; font-size:12px; color:var(--dim);
           border-top:1px solid var(--border); padding-top:10px; }}
  .stats b {{ color:var(--text); }}
  .stats .rel {{ margin-left:auto; font-style:italic; }}
  .empty {{ grid-column:1/-1; text-align:center; color:var(--dim); padding:60px; }}
  footer {{ margin-top:32px; color:var(--dim); font-size:12px; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="star">☤</span> Skill Hermes đã học</h1>
    <div class="sub">Khoảng: {esc(period)} · Tạo lúc {esc(now_str)} · Nguồn: ~/.hermes/skills/.usage.json</div>
  </header>
  <div class="summary">
    <div class="stat-box"><div class="num">{total}</div><div class="lbl">Skill có hoạt động</div></div>
    <div class="stat-box"><div class="num">{new_count}</div><div class="lbl">Mới tạo</div></div>
    <div class="stat-box"><div class="num">{total_uses}</div><div class="lbl">Tổng lượt dùng</div></div>
  </div>
  <div class="grid">
    {''.join(cards)}
  </div>
  <footer>Chỉ hiển thị skill do <b>agent tự tạo</b> (created_by=agent). Skill bundled/hub không nằm trong telemetry này.</footer>
</div>
</body>
</html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="Báo cáo HTML skill agent đã học/tạo trong N ngày qua")
    ap.add_argument("--days", type=int, default=7, help="Số ngày nhìn lại (mặc định 7)")
    ap.add_argument("--all", action="store_true", help="Bỏ lọc thời gian, hiện tất cả")
    ap.add_argument("--no-open", action="store_true", help="Không tự mở trình duyệt")
    ap.add_argument("--out", type=str, default="", help="Đường dẫn file HTML output")
    args = ap.parse_args()

    days = None if args.all else args.days
    rows = collect(days)
    out_html = render_html(rows, days)

    out_path = Path(args.out) if args.out else (hermes_home() / "skills_weekly_report.html")
    out_path.write_text(out_html, encoding="utf-8")
    print(f"✅ Đã tạo report: {out_path}  ({len(rows)} skill)")
    if not args.no_open:
        webbrowser.open(out_path.resolve().as_uri())


if __name__ == "__main__":
    main()
