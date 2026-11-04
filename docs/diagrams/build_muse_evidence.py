"""Render Muse Code evidence from docs/muse-code/runs.json.

runs.json is extracted from Muse Code's own local session log
(~/.local/share/muse/sessions/<date>/<session>/session.jsonl): the exact
prompt sent, Muse's final reply, model, duration, tool calls and tokens.
Personal paths and names are redacted. This script only formats that data:
docs/img/muse-code/run-<n>.png and docs/muse-code/EVIDENCE.md.
"""

import html
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
RUNS = json.loads((ROOT / "docs" / "muse-code" / "runs.json").read_text(encoding="utf-8"))
IMG = ROOT / "docs" / "img" / "muse-code"

CSS = """
body { margin: 0; background: #fff; font-family: Inter, 'Segoe UI', Arial, sans-serif; }
.term { width: 1300px; margin: 24px; border-radius: 12px; overflow: hidden; background: #0f172a; color: #e2e8f0;
        box-shadow: 0 6px 24px rgba(15,23,42,.25); font-family: 'JetBrains Mono', Consolas, monospace; }
.bar { background: #1e293b; padding: 10px 16px; display: flex; gap: 8px; align-items: center; font-size: 15px; color: #94a3b8; }
.dot { width: 12px; height: 12px; border-radius: 50%; display: inline-block; }
.body { padding: 18px 22px 20px; font-size: 16px; line-height: 1.5; }
.lbl { color: #a78bfa; font-weight: 700; margin-top: 10px; }
.you { color: #7dd3fc; font-weight: 700; }
.txt { white-space: pre-wrap; word-break: break-word; }
.dim { color: #94a3b8; }
.muse { color: #86efac; font-weight: 700; }
.foot { border-top: 1px solid #334155; margin-top: 14px; padding-top: 10px; color: #94a3b8; font-size: 14px; display: flex; flex-wrap: wrap; gap: 18px; }
.foot b { color: #e2e8f0; }
.src { font-family: Inter, sans-serif; color: #64748b; font-size: 14px; margin: 0 24px 18px; }
"""


def clip(text, lines, width=118):
    out = []
    for raw in (text or "").splitlines():
        raw = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", raw)
        while len(raw) > width:
            out.append(raw[:width]); raw = raw[width:]
        out.append(raw)
    out = [l for l in out]
    more = len(out) > lines
    return "\n".join(out[:lines]) + ("\n…" if more else "")


def card(n, run):
    tools = ", ".join(f"{k} ×{v}" for k, v in sorted(run["tool_breakdown"].items(), key=lambda kv: -kv[1]))
    return f"""<div class='term'><div class='bar'><span class='dot' style='background:#ef4444'></span>
<span class='dot' style='background:#f59e0b'></span><span class='dot' style='background:#22c55e'></span>
<span style='margin-left:10px'>muse — FaultCase · run {n} of 8 · {html.escape(run['title'])}</span></div>
<div class='body'><div class='you'>&gt; prompt</div><div class='txt'>{html.escape(clip(run['prompt'], 9))}</div>
<div class='lbl'>Muse Code ({html.escape(run['model'])})</div>
<div class='txt'>{html.escape(clip(run['final_reply'], 16))}</div>
<div class='foot'><span>⏱ <b>{run['duration_min']} min</b></span><span>tool calls <b>{run['tool_calls']}</b> ({html.escape(tools)})</span>
<span>tokens in/out <b>{run['input_tokens']:,} / {run['output_tokens']:,}</b></span><span>run <b>{run['run_id'][:13]}</b></span></div>
</div></div><p class='src'>Rendered from Muse Code's local session log (session.jsonl), not retyped. Full prompt and reply: docs/muse-code/EVIDENCE.md</p>"""


def main():
    IMG.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1350, "height": 900}, device_scale_factor=2)
        for n, run in enumerate(RUNS, 1):
            page.set_content(f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{card(n, run)}</body></html>")
            page.screenshot(path=str(IMG / f"run-{n}.png"), full_page=True)
        browser.close()
    md = ["# Muse Code evidence", "",
          "Extracted from Muse Code's own local session log (`~/.local/share/muse/sessions/.../session.jsonl`).",
          "Each entry is the exact prompt sent to Muse Code and Muse's final reply, with the run's model, duration,",
          "tool calls and tokens as Muse Code recorded them. Personal paths and names are redacted; nothing else is edited.", ""]
    for n, run in enumerate(RUNS, 1):
        md += [f"## {n}. {run['title']}", "",
               f"- Run: `{run['run_id']}` · model `{run['model']}` · {run['duration_min']} min · {run['tool_calls']} tool calls"
               f" · {run['input_tokens']:,} input / {run['output_tokens']:,} output tokens",
               f"- Commits named in the reply: {', '.join('`'+c+'`' for c in run['commits_in_reply']) or 'see the reply'}", "",
               f"![Run {n}](../img/muse-code/run-{n}.png)", "",
               "<details><summary>Full prompt</summary>", "", "```text", run["prompt"], "```", "", "</details>", "",
               "**Muse Code's final reply**", "", run["final_reply"], ""]
        if run["progress_messages"]:
            md += ["<details><summary>Progress messages during the run</summary>", ""]
            md += [f"- {m}" for m in run["progress_messages"]] + ["", "</details>", ""]
    (ROOT / "docs" / "muse-code" / "EVIDENCE.md").write_text("\n".join(md), encoding="utf-8")
    print("wrote", len(RUNS), "cards and EVIDENCE.md")


if __name__ == "__main__":
    main()
