"""Convert tau2 results.json into ATIF trajectories (one per task).

  python3 deploy/tacc/bench/tau2_to_atif.py <results.json> <out.jsonl>
"""

import json
import sys
from pathlib import Path


def convert(results):
    out = []
    for sim in results.get("simulations", []):
        steps = []
        for i, msg in enumerate(sim.get("messages") or [], 1):
            role = msg.get("role")
            steps.append(
                {
                    "step_id": i,
                    "timestamp": msg.get("timestamp"),
                    "source": "user" if role == "user" else "assistant",
                    "message": (msg.get("content") or "").strip(),
                    "metrics": {
                        "prompt_tokens": (msg.get("usage") or {}).get("prompt_tokens"),
                        "completion_tokens": (msg.get("usage") or {}).get("completion_tokens"),
                    }
                    if msg.get("usage")
                    else None,
                }
            )
        out.append(
            {
                "schema_version": "ATIF-v1.8",
                "session_id": f"tau2-task{sim.get('task_id')}-{sim.get('trial', 0)}",
                "agent": {"name": "bare-llm", "version": "1", "model_name": "qwen3.8-27b"},
                "steps": steps,
                "final_metrics": {"total_steps": len(steps)},
                "extra": {
                    "task_id": sim.get("task_id"),
                    "duration_s": round(sim.get("duration") or 0, 1),
                    "termination": sim.get("termination_reason"),
                    "reward": (sim.get("reward_info") or {}).get("reward"),
                    "error": (sim.get("info") or {}).get("error"),
                },
            }
        )
    return out


def main():
    results = json.loads(Path(sys.argv[1]).read_text())
    out = Path(sys.argv[2])
    trajs = convert(results)
    out.write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in trajs), encoding="utf-8")
    print(f"{out}  ({len(trajs)} trajectories, {sum(len(t['steps']) for t in trajs)} steps)")


if __name__ == "__main__":
    main()
