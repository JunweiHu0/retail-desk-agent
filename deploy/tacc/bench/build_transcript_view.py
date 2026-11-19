"""Render a transcript view for a tau2 experiment directory.

Reads `atif.jsonl` (one trajectory per task) and `results.json` (tau2 output)
and writes `view.html`: what the user said, what the model said, in order.

  python3 deploy/tacc/bench/build_transcript_view.py docs/experiments/<dir>
"""

import html
import json
import sys
from pathlib import Path


CHART_JS = """
const TURNS = __TURNS__;
function drawLine(host, key, unit) {
  const pts = TURNS.map((t, i) => [i, t[key]]).filter(p => p[1] != null);
  if (pts.length < 2) { host.innerHTML = '<div style="color:var(--muted);font-size:12px">没有数据</div>'; return; }
  const ys = pts.map(p => p[1]);
  const lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
  const span = hi - lo || 1;
  const W = 800, H = 120, L = 44, R = 10, T = 8, B = 18;
  const x = i => L + (i / Math.max(1, pts.length - 1)) * (W - L - R);
  const y = v => H - B - ((v - lo) / span) * (H - T - B);
  let s = '<svg viewBox="0 0 ' + W + ' ' + H + '">';
  [0, 0.5, 1].forEach(function (f) {
    const v = Math.round(lo + span * f), yy = y(v);
    s += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + yy + '" y2="' + yy + '" stroke="var(--line)"/>';
    s += '<text x="' + (L - 6) + '" y="' + (yy + 3) + '" text-anchor="end" font-size="9" fill="var(--muted)">' + v + '</text>';
  });
  s += '<polyline points="' + pts.map(function (p, i) { return x(i) + "," + y(p[1]); }).join(" ") +
       '" fill="none" stroke="var(--u)" stroke-width="1.4"/></svg>';
  host.innerHTML = s;
  const tip = document.createElement('div');
  tip.className = 'ttip';
  host.appendChild(tip);
  const svg = host.querySelector('svg');
  svg.addEventListener('mousemove', function (ev) {
    const r = svg.getBoundingClientRect();
    const i = Math.round((ev.clientX - r.left) / r.width * (pts.length - 1));
    const p = pts[Math.max(0, Math.min(pts.length - 1, i))];
    const t = TURNS[p[0]];
    tip.textContent = 'task ' + t.task + ' · 第 ' + t.turn + ' 轮 · ' + p[1] + ' ' + unit;
    tip.style.left = (ev.clientX - r.left + 12) + 'px';
    tip.style.top = (ev.clientY - r.top - 26) + 'px';
    tip.style.opacity = 1;
  });
  svg.addEventListener('mouseleave', function () { tip.style.opacity = 0; });
}
drawLine(document.getElementById('c-ttft'), 'ttft', 'ms');
drawLine(document.getElementById('c-tpot'), 'tpot', 'ms');
drawLine(document.getElementById('c-kv'), 'kv', '%');
"""


def load(run_dir):
    trajs = [json.loads(l) for l in (run_dir / "atif.jsonl").read_text().splitlines() if l]
    results = None
    if (run_dir / "results.json").is_file():
        results = json.loads((run_dir / "results.json").read_text())
    turns = []
    if (run_dir / "turns.jsonl").is_file():
        turns = [json.loads(l) for l in (run_dir / "turns.jsonl").read_text().splitlines() if l]
    return trajs, results, turns


def metrics_line(row):
    if not row:
        return ""
    parts = []
    if row.get("engine_ttft_ms") is not None:
        parts.append(f"TTFT {row['engine_ttft_ms']} ms")
    if row.get("engine_tpot_ms") is not None:
        parts.append(f"TPOT {row['engine_tpot_ms']} ms")
    if row.get("engine_kv_pct_max") is not None:
        parts.append(f"KV 峰值 {row['engine_kv_pct_max']}%")
    if row.get("engine_gen_tokens"):
        parts.append(f"引擎生成 {row['engine_gen_tokens']} token")
    if row.get("engine_cache_hit") is not None:
        parts.append(f"缓存命中 {row['engine_cache_hit'] * 100:.0f}%")
    parts.append(f"用时 {row['duration_s']} s")
    return f'<div class="met">{" · ".join(parts)}</div>'


def bubbles(steps, turns_by_end=None):
    out = []
    for step in steps:
        source = step.get("source")
        role = "用户" if source == "user" else "模型" if source in ("agent", "assistant") else "系统"
        cls = "u" if source == "user" else "a"
        text = html.escape(str(step.get("message") or ""))
        row = (turns_by_end or {}).get(step.get("timestamp"))
        out.append(
            f'<div class="msg {cls}"><div class="who">{role}</div>'
            f'<div class="txt">{text or "（空）"}{metrics_line(row)}</div></div>'
        )
    return "".join(out)


def build(trajs, results, turns=None):
    sims = {str(s.get("task_id")): s for s in (results or {}).get("simulations", [])}
    cards = []
    first_id = str((trajs[0].get("extra") or {}).get("task_id")) if trajs else ""
    for traj in trajs:
        task_id = str((traj.get("extra") or {}).get("task_id"))
        sim = sims.get(task_id, {})
        duration = sim.get("duration")
        termination = sim.get("termination_reason") or (traj.get("extra") or {}).get("termination")
        turns_by_end = {
            r["end"]: r for r in (turns or []) if str(r.get("task_id")) == str(task_id)
        }
        reward = (sim.get("reward_info") or {}).get("reward")
        mark = " ✓" if reward == 1.0 else ""
        opened = " open" if task_id == first_id else ""
        cards.append(
            f'<details class="card"{opened}><summary>task {html.escape(task_id)}{mark}'
            f'<span class="m">{len(traj["steps"])} 条消息'
            f'{" · " + f"{duration:.1f} s" if duration else ""}'
            f'{" · " + html.escape(str(termination)) if termination else ""}</span></summary>'
            f'<div class="chat">{bubbles(traj["steps"], turns_by_end)}</div></details>'
        )
    tposts = [t["engine_tpot_ms"] for t in (turns or []) if t.get("engine_tpot_ms")]
    kvs = [t["engine_kv_pct_max"] for t in (turns or []) if t.get("engine_kv_pct_max") is not None]
    tp = f"{sum(tposts) / len(tposts):.1f}" if tposts else "–"
    kv = f"{max(kvs):.1f}" if kvs else "–"

    page = f"""<!doctype html>
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
.card summary{{cursor:pointer;font-size:14.5px;display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;list-style:none}}
.card summary::-webkit-details-marker{{display:none}}
.card summary::before{{content:"▸";color:var(--muted);font-size:12px}}
.card[open] summary::before{{content:"▾"}}
.card summary .m{{font-size:12px;color:var(--muted);font-weight:400}}
.card[open] summary{{margin-bottom:10px}}
.chart{{margin:6px 0 12px;position:relative}}
.chart .lab{{font-size:12px;color:var(--muted);margin-bottom:2px}}
.chart svg{{display:block;width:100%;height:auto}}
.ttip{{position:absolute;pointer-events:none;background:var(--ink);color:var(--bg);font-size:11.5px;
  padding:4px 7px;border-radius:5px;opacity:0;transition:opacity .12s;white-space:nowrap;
  font-family:ui-monospace,monospace;z-index:5}}
.tools{{margin:0 0 14px;display:flex;gap:8px}}
.tools button{{font:inherit;font-size:12.5px;padding:4px 10px;border-radius:6px;border:1px solid var(--line);
  background:var(--surface);color:var(--ink);cursor:pointer}}
.msg{{display:grid;grid-template-columns:56px 1fr;gap:10px;padding:8px 0;border-top:1px solid var(--line)}}
.msg:first-child{{border-top:0}}
.who{{font-size:12px;color:var(--muted);padding-top:2px}}
.msg.u .who{{color:var(--u);font-weight:600}}
.txt{{white-space:pre-wrap;font-size:14px}}
.met{{margin-top:6px;font:11.5px ui-monospace,monospace;color:var(--muted)}}
</style></head><body><main>
<h1>无工具基线的对话</h1>
<p class="sub">同一模型、同一政策，但没有任何工具。它只能解释自己做不到，任务因此全部失败——这是质量对比的地板。</p>
<div class="tiles">
  <div class="tile"><div class="k">Pass^1</div><div class="v">0.000</div></div>
  <div class="tile"><div class="k">任务数</div><div class="v">{len(trajs)}</div></div>
  <div class="tile"><div class="k">DB 对比</div><div class="v">0 / {len(trajs)}</div></div>
  <div class="tile"><div class="k">平均 TPOT</div><div class="v">{tp} ms</div></div>
  <div class="tile"><div class="k">KV 峰值</div><div class="v">{kv}%</div></div>
</div>
<section class="card" style="margin-bottom:14px;position:relative">
  <h2 style="font-size:14.5px;margin:0 0 2px">全部轮次的引擎指标</h2>
  <div style="color:var(--muted);font-size:12.5px;margin-bottom:10px">
    横轴是时间顺序的轮次，纵轴毫秒。悬停看是哪一轮。</div>
  <div class="chart"><div class="lab">TTFT（首 token）</div><div id="c-ttft"></div></div>
  <div class="chart"><div class="lab">TPOT（每 token）</div><div id="c-tpot"></div></div>
  <div class="chart"><div class="lab">KV 占用峰值 %</div><div id="c-kv"></div></div>
</section>

<div class="tools"><button id="expand">全部展开</button><button id="collapse">全部收起</button></div>
{"".join(cards)}
</main>
<script>
__CHARTS__
document.getElementById("expand").onclick = () => document.querySelectorAll("details.card").forEach(d => d.open = true);
document.getElementById("collapse").onclick = () => document.querySelectorAll("details.card").forEach(d => d.open = false);
</script>
</body></html>"""
    turns_json = [
        {"task": t.get("task_id"), "turn": t.get("turn"),
         "ttft": t.get("engine_ttft_ms"), "tpot": t.get("engine_tpot_ms"),
         "kv": t.get("engine_kv_pct_max")}
        for t in (turns or [])
    ]
    return page.replace("__CHARTS__", CHART_JS.replace("__TURNS__", json.dumps(turns_json)))


def main():
    run_dir = Path(sys.argv[1])
    trajs, results, turns = load(run_dir)
    (run_dir / "view.html").write_text(build(trajs, results, turns), encoding="utf-8")
    print(f"{run_dir / 'view.html'}  ({len(trajs)} trajectories)")


if __name__ == "__main__":
    main()
