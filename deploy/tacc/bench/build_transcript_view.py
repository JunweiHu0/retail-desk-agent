"""Render a transcript view for a tau2 experiment directory.

Reads `atif.jsonl` (one trajectory per task) and `results.json` (tau2 output)
and writes `view.html`: what the user said, what the model said, in order.

  python3 deploy/tacc/bench/build_transcript_view.py docs/experiments/<dir>
"""

import html
import json
import sys
from pathlib import Path


def load(run_dir):
    trajs = [json.loads(l) for l in (run_dir / "atif.jsonl").read_text().splitlines() if l]
    results = None
    if (run_dir / "results.json").is_file():
        results = json.loads((run_dir / "results.json").read_text())
    return trajs, results


def bubbles(steps):
    out = []
    for step in steps:
        source = step.get("source")
        role = "用户" if source == "user" else "模型" if source in ("agent", "assistant") else "系统"
        cls = "u" if source == "user" else "a"
        text = html.escape(str(step.get("message") or ""))
        out.append(
            f'<div class="msg {cls}"><div class="who">{role}</div>'
            f'<div class="txt">{text or "（空）"}</div></div>'
        )
    return "".join(out)


def build(trajs, results):
    sims = {str(s.get("task_id")): s for s in (results or {}).get("simulations", [])}
    cards = []
    for traj in trajs:
        task_id = str((traj.get("extra") or {}).get("task_id"))
        sim = sims.get(task_id, {})
        duration = sim.get("duration")
        termination = sim.get("termination_reason") or (traj.get("extra") or {}).get("termination")
        cards.append(
            f'<section class="card"><h2>task {html.escape(task_id)}'
            f'<span class="m">{len(traj["steps"])} 条消息'
            f'{" · " + f"{duration:.1f} s" if duration else ""}'
            f'{" · " + html.escape(str(termination)) if termination else ""}</span></h2>'
            f'<div class="chat">{bubbles(traj["steps"])}</div></section>'
        )
    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>无工具基线对话</title>
<style>
:root{{--bg:#fbfbf9;--surface:#fff;--ink:#16161a;--muted:#6b6b72;--line:#e4e3dd;--tile:#f3f2ec;--u:#2a78d6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#121211;--surface:#1a1a19;--ink:#f0efec;--muted:#a3a29a;
  --line:#2f2f2c;--tile:#201f1d;--u:#3987e5}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 system-ui,-apple-system,"Segoe UI",sans-serif;
  padding:24px max(16px,env(safe-area-inset-left,0px)) 48px}}
main{{max-width:900px;margin:0 auto}}
h1{{font-size:24px;margin:0 0 6px}}
.sub{{color:var(--muted);font-size:13.5px;margin-bottom:20px}}
.tiles{{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:22px}}
.tile{{background:var(--tile);border-radius:10px;padding:10px 14px;min-width:130px}}
.tile .k{{font-size:12px;color:var(--muted)}} .tile .v{{font:600 20px ui-monospace,monospace;margin-top:2px}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:14px}}
.card h2{{font-size:14.5px;margin:0 0 10px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}}
.card h2 .m{{font-size:12px;color:var(--muted);font-weight:400}}
.msg{{display:grid;grid-template-columns:56px 1fr;gap:10px;padding:8px 0;border-top:1px solid var(--line)}}
.msg:first-child{{border-top:0}}
.who{{font-size:12px;color:var(--muted);padding-top:2px}}
.msg.u .who{{color:var(--u);font-weight:600}}
.txt{{white-space:pre-wrap;font-size:14px}}
</style></head><body><main>
<h1>无工具基线的对话</h1>
<p class="sub">同一模型、同一政策，但没有任何工具。它只能解释自己做不到，任务因此全部失败——这是质量对比的地板。</p>
<div class="tiles">
  <div class="tile"><div class="k">Pass^1</div><div class="v">0.000</div></div>
  <div class="tile"><div class="k">任务数</div><div class="v">{len(trajs)}</div></div>
  <div class="tile"><div class="k">DB 对比</div><div class="v">0 / {len(trajs)}</div></div>
</div>
{"".join(cards)}
</main></body></html>"""


def main():
    run_dir = Path(sys.argv[1])
    trajs, results = load(run_dir)
    (run_dir / "view.html").write_text(build(trajs, results), encoding="utf-8")
    print(f"{run_dir / 'view.html'}  ({len(trajs)} trajectories)")


if __name__ == "__main__":
    main()
