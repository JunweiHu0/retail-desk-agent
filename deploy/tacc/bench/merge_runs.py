"""Merge several tau2 result directories into one experiment directory.

tau2 refuses to resume across different task sets, so a split run produces one
checkpoint per batch. This joins them back into a single results.json plus one
metrics.jsonl, keeping per-turn timestamps absolute so the sampler windows still
line up.

  python3 deploy/tacc/bench/merge_runs.py <out-dir> <run-dir> [<run-dir> ...]
"""

import json
import sys
from pathlib import Path


def main():
    out = Path(sys.argv[1])
    runs = [Path(p) for p in sys.argv[2:]]
    out.mkdir(parents=True, exist_ok=True)

    sims, info, samples = {}, None, []
    for run in runs:
        data = json.loads((run / "results.json").read_text())
        info = info or data.get("info")
        for sim in data.get("simulations", []):
            sims[(str(sim.get("task_id")), sim.get("trial", 0))] = sim
        metrics = run / "metrics.jsonl"
        if metrics.is_file():
            samples += [json.loads(l) for l in metrics.read_text().splitlines() if l.strip()]

    merged = {
        "timestamp": json.loads((runs[0] / "results.json").read_text()).get("timestamp"),
        "info": info,
        "simulations": [sims[k] for k in sorted(sims, key=lambda k: int(k[0]) if k[0].isdigit() else k[0])],
    }
    (out / "results.json").write_text(json.dumps(merged, ensure_ascii=False, indent=1), encoding="utf-8")

    samples.sort(key=lambda s: s["t"])
    (out / "metrics.jsonl").write_text("".join(json.dumps(s) + "\n" for s in samples), encoding="utf-8")

    valid = [s for s in merged["simulations"] if s.get("termination_reason") == "user_stop"]
    print(f"merged {len(runs)} runs -> {len(merged['simulations'])} tasks "
          f"({len(valid)} valid), {len(samples)} engine samples")


if __name__ == "__main__":
    main()
