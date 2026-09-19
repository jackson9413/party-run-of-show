"""
Flask app for Party Run-of-Show.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime
from flask import Flask, render_template, request, jsonify, abort

from blocks import BLOCKS, OCCASION_TEMPLATES, all_occasion_keys, get_block
from generator import (
    parse_brief, merge_defaults, generate_run_of_show,
    verdict_for,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "sessions.db")

app = Flask(__name__, template_folder="templates", static_folder="static")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            occasion TEXT NOT NULL,
            brief TEXT,
            input_json TEXT NOT NULL,
            output_json TEXT NOT NULL,
            rating INTEGER,
            notes TEXT
        );
    """)
    conn.commit()
    conn.close()


# ---------- ROUTES ----------
@app.route("/")
def index():
    return render_template("index.html",
                           occasions=OCCASION_TEMPLATES,
                           occasion_keys=all_occasion_keys())


@app.route("/api/generate", methods=["POST"])
def api_generate():
    payload = request.get_json(force=True) or {}
    brief = payload.get("brief", "").strip()
    if not brief:
        return jsonify({"error": "brief required"}), 400
    parsed = parse_brief(brief)
    info = merge_defaults(parsed)
    if info["occasion"] not in OCCASION_TEMPLATES:
        return jsonify({"error": f"could not detect occasion (got: {info['occasion']})"}), 400

    # Optional overrides from request
    if payload.get("group_size"):
        try:
            info["group_size"] = int(payload["group_size"])
        except (TypeError, ValueError):
            pass
    if payload.get("total_minutes"):
        try:
            info["total_minutes"] = int(payload["total_minutes"])
        except (TypeError, ValueError):
            pass
    if payload.get("energy_target"):
        info["energy_target"] = payload["energy_target"]
    if payload.get("ages"):
        info["ages"] = payload["ages"]
    if "conflict_safe" in payload:
        info["conflict_safe"] = bool(payload["conflict_safe"])

    result = generate_run_of_show(info)

    # Auto-save session
    try:
        conn = db()
        conn.execute(
            "INSERT INTO sessions (created_at, occasion, brief, input_json, output_json) VALUES (?, ?, ?, ?, ?)",
            (datetime.utcnow().isoformat(), info["occasion"], brief, json.dumps(info), json.dumps(result)),
        )
        conn.commit()
        conn.close()
    except Exception as e:  # pragma: no cover
        app.logger.warning(f"session save failed: {e}")

    return jsonify(result)


@app.route("/api/rate", methods=["POST"])
def api_rate():
    payload = request.get_json(force=True) or {}
    sid = payload.get("session_id")
    rating = payload.get("rating")
    notes = payload.get("notes", "")
    if not sid:
        return jsonify({"error": "session_id required"}), 400
    conn = db()
    conn.execute(
        "UPDATE sessions SET rating = ?, notes = ? WHERE id = ?",
        (rating, notes, sid),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


@app.route("/api/sessions")
def api_sessions():
    conn = db()
    rows = conn.execute("SELECT id, created_at, occasion, brief, rating, notes FROM sessions ORDER BY id DESC LIMIT 50").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route("/api/session/<int:sid>")
def api_session(sid):
    conn = db()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    d = dict(row)
    d["input"] = json.loads(d.pop("input_json"))
    d["output"] = json.loads(d.pop("output_json"))
    return jsonify(d)


@app.route("/api/export/<int:sid>.md")
def api_export_md(sid):
    conn = db()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    out = json.loads(row["output_json"])
    md = render_markdown(out)
    return md, 200, {"Content-Type": "text/markdown; charset=utf-8",
                     "Content-Disposition": f'attachment; filename="run-of-show-{sid}.md"'}


@app.route("/api/export/<int:sid>.json")
def api_export_json(sid):
    conn = db()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    out = json.loads(row["output_json"])
    return jsonify(out)


def render_markdown(out):
    info = out["input"]
    lines = []
    lines.append(f"# Party Run-of-Show — {out['template']}")
    lines.append("")
    lines.append(f"- **Occasion:** {out['template']}")
    lines.append(f"- **Group size:** {info.get('group_size')}")
    lines.append(f"- **Ages:** {info.get('ages')}")
    lines.append(f"- **Total window:** {out['requested_minutes']} min")
    lines.append(f"- **Actual run-time:** {out['actual_minutes']} min")
    lines.append(f"- **Energy target:** {info.get('energy_target')}")
    lines.append(f"- **Verdict:** {out['verdict']} ({out['scoring']['overall']}/100)")
    lines.append("")
    lines.append("## Timeline")
    lines.append("")
    lines.append("| # | Stage | Time | Title | Min | Energy |")
    lines.append("|---|-------|------|-------|-----|--------|")
    for i, b in enumerate(out["timeline"], 1):
        sh = b["start_offset"] // 60
        sm = b["start_offset"] % 60
        eh = b["end_offset"] // 60
        em = b["end_offset"] % 60
        lines.append(f"| {i} | {b['stage_label']} | {sh:02d}:{sm:02d}-{eh:02d}:{em:02d} | {b['title']} | {b['minutes']} | {b['energy_label']} |")
    lines.append("")
    lines.append("## Block Details")
    lines.append("")
    for i, b in enumerate(out["timeline"], 1):
        lines.append(f"### {i}. {b['title']}")
        lines.append(f"- **Stage:** {b['stage_label']}")
        lines.append(f"- **Energy:** {b['energy_label']} | **Noise:** {b['noise']}")
        if b.get("materials"):
            lines.append(f"- **Materials:** {', '.join(b['materials'])}")
        lines.append(f"- **Why this slot:** {b['rationale']}")
        lines.append("")
    lines.append("## Scoring")
    lines.append("")
    for k, v in out["scoring"]["axes"].items():
        w = int(out["scoring"]["weights"][k] * 100)
        lines.append(f"- **{k}** ({w}%): {v}/100")
    lines.append(f"- **Overall:** {out['scoring']['overall']}/100 — {out['verdict']}")
    lines.append("")
    lines.append("## Insights")
    lines.append("")
    for x in out["insights"]:
        lines.append(f"- {x}")
    lines.append("")
    if out.get("flags"):
        lines.append("## Flags")
        lines.append("")
        for x in out["flags"]:
            lines.append(f"- ⚠ {x}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5003)
