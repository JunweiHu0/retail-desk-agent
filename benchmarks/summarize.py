"""Generate an evidence-based report from one saved official tau2 Results object."""

import argparse
import json
from collections import Counter
from pathlib import Path

from backend import config


def summarize(path):
    data = json.loads(Path(path).read_text())
    sims = data["simulations"]
    tasks = {t["id"]: t for t in data["tasks"]}
    rows = []
    matched = Counter()
    expected = Counter()
    for sim in sims:
        reward = sim["reward_info"]
        for check in reward.get("action_checks") or []:
            expected[check["tool_type"]] += 1
            if check["action_match"]:
                matched[check["tool_type"]] += 1
        calls = [
            call
            for msg in sim["messages"]
            for call in msg.get("tool_calls") or []
            if msg["role"] == "assistant"
        ]
        failed = [c for c in reward.get("nl_assertions") or [] if not c["met"]]
        rows.append(
            {
                "task_id": sim["task_id"],
                "reward": reward["reward"],
                "db_match": reward["db_check"]["db_match"],
                "duration_seconds": sim["duration"],
                "tool_calls": len(calls),
                "trial_seed": sim["seed"],
                "termination": sim["termination_reason"],
                "first_tool": calls[0]["name"] if calls else None,
                "scenario": tasks[sim["task_id"]]["user_scenario"]["instructions"][
                    "reason_for_call"
                ],
                "failed_assertions": failed,
            }
        )
    report = {
        "date": "2026-10-27",
        "agent": data["info"]["agent_info"]["llm"],
        "user_simulator": data["info"]["user_info"]["llm"],
        "nl_judge": data["info"]["communicate_scoring"]["judge"]["model"],
        "configured_seed": data["info"]["seed"],
        "num_trials": data["info"]["num_trials"],
        "sample_selection": "first five English Retail base tasks, IDs 0-4; not a random representative sample",
        "task_count": len(sims),
        "passed": sum(r["reward"] == 1 for r in rows),
        "success_rate": sum(r["reward"] == 1 for r in rows) / len(rows),
        "db_matches": sum(r["db_match"] for r in rows),
        "read_action_matches": {"matched": matched["read"], "expected": expected["read"]},
        "write_action_matches": {"matched": matched["write"], "expected": expected["write"]},
        "mean_conversation_duration_seconds": sum(r["duration_seconds"] for r in rows) / len(rows),
        "cost_usd": None,
        "cost_note": "Provider cost unavailable; do not interpret a zero fallback as free usage.",
        "rows": rows,
    }
    destination = config.ROOT / "docs/reports"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "retail-baseline-20261027.raw.json").write_text(Path(path).read_text())
    (destination / "retail-baseline-20261027.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2)
    )
    names = {
        "0": "键盘与温控器换货（包含备选规格）",
        "1": "仅温控器换货（保留键盘）",
        "2": "查询 T 恤库存并退货",
        "3": "修改待处理小码 T 恤并查询库存",
        "4": "修改多笔 T 恤订单并查询库存",
    }
    lines = [
        "# Retail 小样本评测报告",
        "",
        "日期：2026-10-27。原始结果由官方 tau2 runner / evaluator 生成，未重写评分。",
        "",
        "## 本次设置",
        "",
        "- Agent：deepagents + deepseek-flash，关闭思考模式。",
        "- 用户模拟器、NL assertion judge：DeepSeek Flash；只使用已有 DeepSeek 凭证。",
        "- 英文 Retail base 任务 0–4，每个任务 1 次；配置 seed=42，官方抽出的 trial seed=670487。",
        "- 每任务最多 80 步、600 秒、并发 1；不因失败重跑，不开启额外 LLM 复审。",
        "- 使用上游任务、业务工具和评分标准；只替换模型。未改动官方任务或 seed 数据。",
        "- 本次不是 frozen text-v1 排行榜提交；用户模型与评分模型有别于官方默认。",
        "",
        "## 结果",
        "",
        f"- 成功：{report['passed']}/{len(sims)}（{report['success_rate']:.0%}）。",
        f"- 最终数据库状态匹配：{report['db_matches']}/{len(sims)}。",
        f"- 预期读操作命中：{matched['read']}/{expected['read']}；预期写操作命中：{matched['write']}/{expected['write']}。",
        f"- 平均对话执行耗时：{report['mean_conversation_duration_seconds']:.1f} 秒（不含后置评分）。",
        "- 5 次均由用户正常结束。成本统计不可用，不将 $0 视作免费。",
        "",
        "| Task | 场景 | 得分 | DB 匹配 | 对话耗时 |",
        "| --- | --- | ---: | --- | ---: |",
    ]
    for r in rows:
        lines.append(
            f"| {r['task_id']} | {names.get(r['task_id'], '')} | {r['reward']:.0f} | {'是' if r['db_match'] else '否'} | {r['duration_seconds']:.1f}s |"
        )
    lines += [
        "",
        "## 两个失败项的证据",
        "",
        "官方 T-Shirt 产品共有 12 个 variant，其中 2 个 available=false，所以可用规格为 10。",
        "- Task 3：Agent 报告 12 个总规格，只提到 1 个缺货，没有明确回答 10 个可用规格；NL assertion 未通过。",
        "- Task 4：Agent 明确回答 11 个可用规格，漏数了一个缺货规格；NL assertion 未通过。",
        "- 两者实际订单修改和最终数据库状态均正确；本轮主要暴露的是结构化结果的计数与回答准确性。",
        "",
        "## 结论与限制",
        "",
        "工具调用、换货、退货和多订单修改在本轮可以完成；库存统计存在不稳定的模型计数问题。",
        "下一步应优先对库存、金额和商品数量增加确定性计算/校验，再用未参与调试的更多任务做回归。不要通过硬编码答案 10 优化。",
        "5 个任务都围绕同一客户 Yusuf Rossi，场景高度相关，60% 不能代表完整 Retail 成功率。",
        "官方输出中的 Authentication 为 Not Checked，额外 LLM Review 未运行；不能把空复审计数当作零安全问题。",
        "",
        "## 数据与产物",
        "",
        "网页库另行新增 6 位演示客户、18 笔订单，总数变为 506 客户 / 1,018 订单。新增数据不参与官方 benchmark。",
        "示例邮箱：li.ming@retail-demo.example.com，订单 #W9000001 / #W9000002 / #W9000003。",
        "客户清单：`docs/demo-customers.json`。数据库写入前备份位于 `runtime/backups/`。",
        "原始官方结果：`runtime/benchmarks/deepseek-retail-20261027/results.json`。",
        "结果副本：`runtime/benchmarks/deepseek-retail-20261027.json`；日志：`runtime/benchmarks/run-20261027.log`。",
        "本目录的 JSON 是从原始结果自动汇总，完整对话位于原始结果文件。",
        "",
        "[完整官方轨迹与评分副本](retail-baseline-20261027.raw.json)",
        "",
        "## 复现",
        "",
        "```bash",
        "cd /home/mnyh/projects/retail-agent",
        "uv run --frozen python -m scripts.seed_demo --apply  # 幂等，不覆盖已有修改",
        "uv run --frozen python -m benchmarks.run_retail --num-tasks 5 --max-steps 80 \\",
        "  --timeout 600 --seed 42 --save-to /home/mnyh/projects/retail-agent/runtime/benchmarks/new-retail-run",
        "```",
        "",
        "新一次调用会产生模型费用，得分可能因模型和模拟用户的随机性变化。",
    ]
    (destination / "retail-baseline-20261027.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    summarize(parser.parse_args().path)
