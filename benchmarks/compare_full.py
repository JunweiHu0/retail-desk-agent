"""Compare two complete Retail runs; retain every raw official reward, including regressions."""

import argparse
import json
from pathlib import Path

from backend.config import ROOT
from benchmarks.full_report import load_summary


def compare(before_path, after_path):
    before, after = load_summary(before_path), load_summary(after_path)
    if before["missing"] or after["missing"]:
        raise ValueError("Cannot report a complete comparison: tasks are missing")
    a = {r["task_id"]: r for r in before["rows"]}
    b = {r["task_id"]: r for r in after["rows"]}
    if a.keys() != b.keys():
        raise ValueError("Task sets differ")
    fixed = [tid for tid in a if a[tid]["reward"] < 1 and b[tid]["reward"] == 1]
    regressed = [tid for tid in a if a[tid]["reward"] == 1 and b[tid]["reward"] < 1]
    unresolved = [tid for tid in a if a[tid]["reward"] < 1 and b[tid]["reward"] < 1]
    fixed, regressed, unresolved = (
        sorted(values, key=int) for values in (fixed, regressed, unresolved)
    )
    result = {
        "date": "2026-10-27",
        "domain": "retail",
        "num_tasks": len(a),
        "baseline": before,
        "optimized": after,
        "fixed_tasks": fixed,
        "regressed_tasks": regressed,
        "unresolved_tasks": unresolved,
    }
    dest = ROOT / "docs/reports"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "retail-full-20261027.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    n = len(a)
    lines = [
        "# 完整 Retail 评测与优化回归",
        "",
        "日期：2026-10-27。",
        "",
        "## 范围与配置",
        "",
        "- 官方 runner 默认英文 Retail base 全集：114 条、ID 0–113，每条 1 次。",
        "- 仓库另有 50 条发布筛选集；本轮使用完整 114 条注册任务，不混淆为 50 条成绩。",
        "- Agent：Deep Agents + deepseek-flash；用户模拟器和 NL 评分器同为 DeepSeek Flash。",
        "- 前后两轮均 seed=42、并发 3、最多 100 步、每任务 600 秒、不按失败分数重试。",
        "- 未修改官方业务工具、任务、预期答案和 reward。网页沙盒与评测数据隔离。",
        "- 两个中间候选分别在 35 条和 76 条停止：前者补同规格政策防护，后者修正混合计划整单拒绝过严。检查点分别保存在 retail-full-after-20261027、retail-full-optimized-20261027。最终版从头跑完 114 条，不拼接中间成绩。",
        "- 不是官方 frozen leaderboard 提交；这是根据完整集失败分析后的同集回归，不是独立未见集成绩。",
        "",
        "## 前后对比",
        "",
        "| 指标 | 基线 | 优化后 |",
        "| --- | ---: | ---: |",
        f"| 完成任务 | {before['completed']}/{n} | {after['completed']}/{n} |",
        f"| 通过任务 | {before['passed']}/{n} | {after['passed']}/{n} |",
        f"| 成功率 | {before['passed'] / n:.1%} | {after['passed'] / n:.1%} |",
        f"| 最终数据库状态匹配 | {before['db_matches']}/{n} | {after['db_matches']}/{n} |",
        f"| 平均对话执行耗时（不含后置评分） | {sum(r['duration'] for r in a.values()) / n:.1f}s | {sum(r['duration'] for r in b.values()) / n:.1f}s |",
        "",
        f"净增加 {after['passed'] - before['passed']} 条通过；提升 {(after['passed'] - before['passed']) / n * 100:.2f} 个百分点。修复与回退同时存在，属于小幅净改善，不能视为稳定的大幅提升。保持 dev 实验分支，不合入 main。",
        "",
        f"修复任务：{', '.join(fixed) or '无'}。",
        "",
        f"回退任务：{', '.join(regressed) or '无'}。",
        "",
        f"两轮都未通过：{', '.join(unresolved) or '无'}。",
        "",
        "## 优化内容",
        "",
        "1. 仅从实际工具返回计算可用/缺货/总规格数、可用最低价和订单商品金额，未使用任务答案或固定数字。",
        "2. 明确同一已送达订单的退货与换货存在状态冲突，先确定优先级再执行。",
        "3. 保留多订单请求的完整范围；回滚仅限用户明确要求的对象，不主动扩展变更。",
        "4. 地址/支付变更在一次性商品修改前完成；收集支付方式与最终确认分开，变更细节后重新确认。",
        "5. 先按库存、规格和预算过滤可行商品，再比较最佳选项；保留客户未要求改变的规格。",
        "6. 优先使用真实原支付方式的清晰描述，尊重用户明确选择，不为匹配预设答案改写用户选择。",
        "",
        "## 全部任务",
        "",
        "| Task | 基线 | 优化后 | 优化后失败类别 |",
        "| --- | ---: | ---: | --- |",
    ]
    for tid in sorted(a, key=int):
        lines.append(
            f"| {tid} | {a[tid]['reward']:.0f} | {b[tid]['reward']:.0f} | {', '.join(b[tid]['categories']) or '—'} |"
        )
    lines += ["", "## 剩余失败的原始评分理由", ""]
    for tid in sorted((k for k in b if b[k]["reward"] < 1), key=int):
        row = b[tid]
        lines += [
            f"### Task {tid}",
            "",
            row["scenario"],
            "",
            f"终止：{row['termination']}；DB 匹配：{row['db_match']}。",
            "",
        ]
        lines += [
            f"- {check['nl_assertion']}\n  - {check['justification']}"
            for check in row["failed_assertions"]
        ]
        lines += [f"- 工具错误：{error}" for error in row["tool_errors"]]
        lines += [
            f"- 未命中预期写操作：`{action['name']}`，参数 `{json.dumps(action['arguments'], ensure_ascii=False)}`。"
            for action in row["missing_writes"]
        ]
        lines.append("")
    lines += [
        "## 解释限制",
        "",
        "仍有真实 Agent 错误，例如未严格执行备选偏好、漏掉可查询地址、把 17.99 口头说成 18.00，不能将所有失败都归因于数据或评分器。",
        "用户模拟器、模型与评分器仍有随机性。部分任务会出现用户明确选择/规格要求与预设写操作不一致，或订单数据缺乏日期却要求判定最近订单。",
        "这些失败保留官方原分，不通过猜测未暴露信息、硬编码任务答案、强制改写用户选择来提升分数。",
        "额外人工/安全 LLM 复审未运行，不能将空复审统计当作零问题。DeepSeek 的费用映射缺失，成本为不可用，不视作免费。",
        "",
        "## 原始产物",
        "",
        f"- 基线：`{before['source']}`",
        f"- 优化后：`{after['source']}`",
        "- 完整逐任务汇总：[JSON](retail-full-20261027.json)。",
        "- [失败审查与候选回归](retail-full-audit-20261027.md)。",
        "- [原始轨迹与检查点 ZIP](retail-full-20261027.zip)。",
        "- 两轮完整对话和官方 reward_info 保留在上述 runtime/benchmarks 目录。",
        "",
    ]
    (dest / "retail-full-20261027.md").write_text("\n".join(lines))
    print(
        json.dumps(
            {
                "n": n,
                "before_passed": before["passed"],
                "after_passed": after["passed"],
                "fixed": fixed,
                "regressed": regressed,
                "unresolved": unresolved,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args()
    compare(args.before, args.after)
