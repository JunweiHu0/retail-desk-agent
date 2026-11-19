"""Build a standalone HTML view of an LLM-side run (run.json + atif.jsonl).

Everything the page shows comes from the model endpoint: per-call latency,
prompt/completion tokens, reasoning volume, and the tool calls the model chose
to emit. Nothing from the application layer is involved, so this page can be
produced for any run that recorded ATIF trajectories.

  python3 deploy/tacc/bench/build_view.py <run-dir> <out.html>
"""

import json
import sys
from pathlib import Path

ON, OFF = "#2a78d6", "#eb6834"


def load(run_dir):
    run = json.loads((run_dir / "run.json").read_text())
    prompt_file = run_dir / "system_prompt.txt"
    run["system_prompt"] = prompt_file.read_text() if prompt_file.is_file() else ""
    rows = [json.loads(line) for line in (run_dir / "atif.jsonl").read_text().splitlines() if line]
    return run, rows


def step_of(traj):
    return next(s for s in traj["steps"] if s["source"] == "agent")


def build(run, rows):
    steps = [step_of(r) for r in rows]
    total = len(steps)
    tool = sum(1 for s in steps if s.get("tool_calls"))
    think_chars = sum(len((s.get("extra") or {}).get("reasoning_content") or "") for s in steps)
    prompt_tok = sum((s.get("metrics") or {}).get("prompt_tokens") or 0 for s in steps)
    gen_tok = sum((s.get("metrics") or {}).get("completion_tokens") or 0 for s in steps)

    data = {
        "run": run,
        "points": [
            {
                "mode": r.get("extra", {}).get("mode"),
                "c": r.get("extra", {}).get("concurrency"),
                "ttft": s["extra"]["ttft_ms"],
                "e2e": s["extra"]["e2e_ms"],
                "tpot": s["extra"]["tpot_ms"],
                "ptok": (s.get("metrics") or {}).get("prompt_tokens"),
                "gtok": (s.get("metrics") or {}).get("completion_tokens"),
                "tools": [c["function_name"] for c in s.get("tool_calls") or []],
                "tool_args": [
                    {"name": c["function_name"], "args": c.get("arguments")}
                    for c in s.get("tool_calls") or []
                ],
                "msg": s.get("message") or "",
                "reason": (s.get("extra") or {}).get("reasoning_content") or "",
                "msg_q": r["steps"][0].get("message") or "",
                "think": len((s.get("extra") or {}).get("reasoning_content") or ""),
                "answer": len(s.get("message") or ""),
            }
            for r, s in zip(rows, steps)
        ],
    }

    import html as _html

    def esc(x):
        return _html.escape(str(x), quote=True)

    summary_rows = "".join(
        "<tr>"
        f"<td>{esc(s.get('mode'))}</td><td>{esc(s.get('concurrency'))}</td>"
        f"<td class='m'>{esc(s.get('ttft_p50_ms'))}</td>"
        f"<td class='m'>{esc(s.get('ttft_p95_ms'))}</td>"
        f"<td class='m'>{esc(s.get('tpot_p50_ms'))}</td>"
        f"<td class='m'>{esc(s.get('e2e_p50_ms'))}</td>"
        f"<td class='m'>{esc(s.get('completion_tokens_avg'))}</td>"
        f"<td class='m'>{round((s.get('tool_call_rate') or 0) * 100)}%</td>"
        f"<td class='m'>{esc(s.get('req_per_s'))}</td>"
        "</tr>"
        for s in run.get("summaries") or []
    )

    pick = [p for p in data["points"] if p["tools"]][:2] + \
           [p for p in data["points"] if not p["tools"]][:2]
    pairs = ""
    for p in pick:
        q = _html.escape(str(p["msg_q"]))
        out = _html.escape(str(p["msg"] or "（空）"))
        tools = ", ".join(t["name"] for t in p["tool_args"]) if p["tool_args"] else "无"
        pairs += (
            '<div class="pair">'
            '<div class="pk">输入 · 用户说</div>'
            f'<div class="pin">{q}</div>'
            '<div class="pk">输出 · 模型说</div>'
            f'<div class="pout">{out}</div>'
            f'<div class="pm">工具调用：{tools} · {p["ptok"]} prompt / '
            f'{p["gtok"]} gen · {p["e2e"]} ms</div>'
            "</div>"
        )

    return f"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LLM 侧运行视图</title>
<style>
:root{{--bg:#fbfbf9;--surface:#fff;--ink:#16161a;--muted:#6b6b72;--line:#e4e3dd;--tile:#f3f2ec;
  --s1:{ON};--s2:{OFF};}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#121211;--surface:#1a1a19;
  --ink:#f0efec;--muted:#a3a29a;--line:#2f2f2c;--tile:#201f1d;--s1:#3987e5;--s2:#d95926;color-scheme:dark}}}}
:root[data-theme="dark"]{{--bg:#121211;--surface:#1a1a19;--ink:#f0efec;--muted:#a3a29a;
  --line:#2f2f2c;--tile:#201f1d;--s1:#3987e5;--s2:#d95926;color-scheme:dark}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 Inter,system-ui,sans-serif;
  padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-block:24px 48px}}
main{{max-width:1120px;margin:0 auto}}
h1{{font-size:28px;margin:0 0 6px}}
.sub{{color:var(--muted);font-size:14px;max-width:72ch}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:20px 0}}
.tile{{background:var(--tile);border-radius:10px;padding:12px 14px}}
.tile .k{{font-size:12.5px;color:var(--muted)}}
.tile .v{{font:600 22px ui-monospace,monospace;margin-top:3px;font-variant-numeric:tabular-nums}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px}}
.card h3{{margin:0 0 8px;font-size:13.5px}}
.leg{{display:flex;gap:14px;font-size:12px;color:var(--muted);margin-bottom:4px}}
.leg i{{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-right:5px}}
svg{{display:block;width:100%;height:auto}}
.tblwrap{{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--surface);margin-top:14px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px}}
th,td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap;
  font-variant-numeric:tabular-nums}}
th:first-child,td:first-child,th:nth-child(2),td:nth-child(2){{text-align:left}}
th{{color:var(--muted);font-weight:500;font-size:11.5px}}
td.m{{font-family:ui-monospace,monospace}}
.req{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:10px}}
.req summary{{cursor:pointer;font-size:13px;color:var(--ink)}}
.req pre{{white-space:pre-wrap;font:12px/1.55 ui-monospace,monospace;color:var(--muted);max-height:340px;overflow:auto;margin:8px 0 0}}
.reqrow{{font-size:13px;margin:4px 0;color:var(--ink)}}
.reqrow b{{display:inline-block;min-width:48px;color:var(--muted);font-weight:500}}
.pairs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px}}
.pair{{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:10px 12px;min-width:0}}
.pk{{font-size:11px;color:var(--muted);letter-spacing:.03em;text-transform:uppercase;margin-top:6px}}
.pin,.pout{{font-size:13px;margin-top:2px;white-space:pre-wrap}}
.pm{{font-size:11.5px;color:var(--muted);margin-top:8px}}
tr.row{{cursor:pointer}}
tr.row:hover td{{background:var(--tile)}}
.drow td{{text-align:left;white-space:normal;background:var(--tile);padding:10px 12px}}
.drow .lab{{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em;margin-top:8px}}
.drow .lab:first-child{{margin-top:0}}
.drow .txt{{font-size:13px;margin-top:2px;white-space:pre-wrap}}
.legend{{font-size:12px;color:var(--muted);margin:8px 2px 0;line-height:1.8}}
.foot{{margin-top:28px;padding-top:12px;border-top:1px solid var(--line);color:var(--muted);font-size:12.5px}}
</style></head>
<body><main>
<h1>LLM 侧运行视图</h1>
<p class="sub">数据全部来自模型端点：每次调用的延迟、token 用量、思考长度，以及模型自己选择发出的工具调用。
不通应用层，一份 ATIF 轨迹就能渲染。</p>
<div class="tiles">
  <div class="tile"><div class="k">模型调用</div><div class="v">{total}</div></div>
  <div class="tile"><div class="k">发出工具调用</div><div class="v">{tool} <small>({tool*100//max(total,1)}%)</small></div></div>
  <div class="tile"><div class="k">prompt token</div><div class="v">{prompt_tok:,}</div></div>
  <div class="tile"><div class="k">生成 token</div><div class="v">{gen_tok:,}</div></div>
  <div class="tile"><div class="k">思考字符</div><div class="v">{think_chars:,}</div></div>
</div>
<h2 style="font-size:15px;margin:26px 0 8px">六格汇总</h2>
<div class="tblwrap" style="margin-top:0"><table>
<thead><tr><th>思考</th><th>并发</th><th>TTFT p50</th><th>TTFT p95</th><th>TPOT p50</th>
<th>e2e p50</th><th>生成 token</th><th>工具调用率</th><th>req/s</th></tr></thead>
<tbody>{summary_rows}</tbody></table></div>

<h2 style="font-size:15px;margin:26px 0 8px">这次请求里放了什么</h2>
<details class="req"><summary>system prompt 全文（{len(run.get("system_prompt") or "")} 字符，含 16 个工具定义另计）</summary>
<pre>{esc(run.get("system_prompt") or "")}</pre></details>
<div class="reqrow"><b>user</b> {esc(data["points"][0]["msg_q"])}</div>
<div class="reqrow"><b>参数</b> temperature=0 · max_tokens=512 · tools={run.get('tool_count')} 个 · stream=true</div>
<div class="reqrow"><b>工具</b> {esc(", ".join(run.get("tool_names") or []))}</div>

<h2 style="font-size:15px;margin:26px 0 8px">输入 → 输出</h2>
<div class="pairs">{pairs}</div>

<h2 style="font-size:15px;margin:26px 0 8px">曲线</h2>
<div class="grid">
  <div class="card"><h3>TTFT · 按并发</h3>
    <div class="leg"><span><i style="background:var(--s1)"></i>思考开</span><span><i style="background:var(--s2)"></i>思考关</span></div>
    <div id="c1"></div></div>
  <div class="card"><h3>端到端 · 按并发</h3>
    <div class="leg"><span><i style="background:var(--s1)"></i>思考开</span><span><i style="background:var(--s2)"></i>思考关</span></div>
    <div id="c2"></div></div>
  <div class="card"><h3>每次调用的生成 token</h3>
    <div class="leg"><span><i style="background:var(--s1)"></i>思考开</span><span><i style="background:var(--s2)"></i>思考关</span></div>
    <div id="c3"></div></div>
  <div class="card"><h3>工具调用分布</h3><div id="c4"></div></div>
</div>
<details><summary style="cursor:pointer;font-size:13px;color:var(--muted);margin-top:14px">逐条明细（{total} 条）</summary>
<div class="tblwrap"><table>
<thead><tr><th>#</th><th>思考</th><th>并发</th><th>TTFT</th><th>e2e</th><th>prompt</th>
<th>gen</th><th>思考字符</th><th>回答字符</th><th>工具调用</th></tr></thead>
<tbody id="tb"></tbody></table></div>
<div class="legend">列含义：<b>TTFT</b> 第一个 token 的等待（ms）· <b>e2e</b> 整次请求耗时（ms）·
<b>prompt</b> 输入 token 数 · <b>gen</b> 输出 token 数 · <b>思考字符</b> 推理文本长度 ·
<b>回答字符</b> 用户看到的文本长度 · <b>工具调用</b> 模型选择调用的函数。点任意一行展开输入输出。</div></details>
<div class="foot">run {run.get('slurm_job_id')} · {run.get('model')} · 系统提示 {run.get('system_prompt_chars')} 字符 ·
{run.get('tool_count')} 个工具 · 数据 atif.jsonl</div>
</main>
<script>
const D = {json.dumps(data, ensure_ascii=False)};
const xs = [1,2,4];
const mean = a => a.length ? a.reduce((x,y)=>x+y,0)/a.length : null;
function cell(mode, c, key) {{
  const v = D.points.filter(p => p.mode===mode && p.c===c).map(p => p[key]).filter(x => x != null);
  return v.length ? Math.round(mean(v)) : null;
}}
function line(host, key, unit) {{
  const rows = xs.map((c,i) => [i, cell("on",c,key), cell("off",c,key)]).filter(r => r[1]!=null || r[2]!=null);
  const max = Math.max(1, ...rows.flatMap(r => [r[1]||0, r[2]||0]));
  const W=480,H=210,L=46,R=12,T=12,B=30;
  const x=i => L + i*(W-L-R)/(xs.length-1);
  const y=v => H-B - (v/max)*(H-T-B);
  let s = `<svg viewBox="0 0 ${{W}} ${{H}}">`;
  [0,.5,1].forEach(f => {{ const v=Math.round(max*f);
    s += `<line x1="${{L}}" x2="${{W-R}}" y1="${{y(v)}}" y2="${{y(v)}}" stroke="var(--line)"/>`;
    s += `<text x="${{L-6}}" y="${{y(v)+4}}" text-anchor="end" font-size="10" fill="var(--muted)">${{v}}</text>`;
  }});
  xs.forEach((c,i) => s += `<text x="${{x(i)}}" y="${{H-10}}" text-anchor="middle" font-size="10.5" fill="var(--muted)">${{c}}</text>`);
  [["on","var(--s1)"],["off","var(--s2)"]].forEach(([m,color]) => {{
    const pts = rows.map(r => {{ const v = m==="on"?r[1]:r[2]; return v==null?null:[x(r[0]), y(v)]; }}).filter(Boolean);
    if (pts.length < 2) return;
    s += `<polyline points="${{pts.map(p=>p.join(",")).join(" ")}}" fill="none" stroke="${{color}}" stroke-width="2"/>`;
    pts.forEach(p => s += `<circle cx="${{p[0]}}" cy="${{p[1]}}" r="4" fill="${{color}}" stroke="var(--surface)" stroke-width="2"/>`);
  }});
  s += `</svg>`;
  host.innerHTML = s;
}}
line(document.getElementById("c1"), "ttft", "ms");
line(document.getElementById("c2"), "e2e", "ms");
line(document.getElementById("c3"), "gtok", "tok");
// tool distribution
const counts = {{}};
D.points.forEach(p => (p.tools||[]).forEach(t => counts[t] = (counts[t]||0)+1));
const items = Object.entries(counts).sort((a,b)=>b[1]-a[1]).slice(0,8);
const mx = Math.max(1, ...items.map(i=>i[1]));
document.getElementById("c4").innerHTML = items.length ? items.map(([name,n]) => `
  <div style="display:flex;align-items:center;gap:8px;margin:5px 0">
    <span style="width:34%;font-size:11.5px;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${{name}}</span>
    <span style="flex:1;height:12px;background:var(--tile);border-radius:3px;overflow:hidden">
      <span style="display:block;height:100%;width:${{n/mx*100}}%;background:var(--s1)"></span></span>
    <span style="font:11.5px ui-monospace,monospace;width:28px;text-align:right">${{n}}</span>
  </div>`).join("") : `<div style="color:var(--muted);font-size:13px">本次没有工具调用</div>`;
const tb = document.getElementById("tb");
const E = s => String(s ?? "").replace(/[&<>"]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c]));
tb.innerHTML = D.points.map((p,i) => `<tr class="row" data-i="${{i}}">
  <td>${{i+1}} ▸</td><td>${{p.mode==="on"?"开":"关"}}</td><td>${{p.c}}</td>
  <td class="m">${{p.ttft ?? "–"}}</td><td class="m">${{p.e2e}}</td>
  <td class="m">${{p.ptok}}</td><td class="m">${{p.gtok}}</td>
  <td class="m">${{p.think}}</td><td class="m">${{p.answer}}</td>
  <td class="m">${{(p.tools||[]).join(", ") || "–"}}</td></tr>
<tr class="drow" id="d${{i}}" hidden><td colspan="10">
  <div class="lab">输入 · 用户说</div><div class="txt">${{E(p.msg_q)}}</div>
  <div class="lab">思考 · 模型内部，用户看不到</div><div class="txt">${{E(p.reason || "（无思考）")}}</div>
  <div class="lab">输出 · 模型说</div><div class="txt">${{E(p.msg || "（空）")}}</div>
  <div class="lab">工具调用</div><div class="txt">${{(p.tool_args||[]).map(t => E(t.name) + "(" + E(JSON.stringify(t.args)) + ")").join("<br>") || "无"}}</div>
  <div class="lab">这些数字</div><div class="txt">TTFT ${{p.ttft}} ms（第一个 token）· e2e ${{p.e2e}} ms（整次）· 输入 ${{p.ptok}} token · 输出 ${{p.gtok}} token</div>
</td></tr>`).join("");
tb.querySelectorAll("tr.row").forEach(tr => tr.onclick = () => {{
  const d = document.getElementById("d" + tr.dataset.i);
  d.hidden = !d.hidden;
}});
</script>
</body></html>"""


def main():
    run_dir = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else run_dir / "view.html"
    run, rows = load(run_dir)
    out.write_text(build(run, rows), encoding="utf-8")
    print(f"{out}  ({len(rows)} steps)")


if __name__ == "__main__":
    main()
