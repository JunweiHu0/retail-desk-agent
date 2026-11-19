"""Compare two bench runs cell by cell.

  python3 deploy/tacc/bench/compare_runs.py baseline/run.json variant/run.json
"""

import json
import sys


def load(path):
    run = json.loads(open(path).read())
    return {(s["mode"], s["concurrency"]): s for s in run["summaries"]}, run


def fmt(v, digits=2):
    return "—" if v is None else f"{v:.{digits}f}"


def pct(new, old):
    if not old:
        return "—"
    return f"{(new - old) / old * 100:+.0f}%"


def main():
    base, base_run = load(sys.argv[1])
    var, var_run = load(sys.argv[2])

    print(f"baseline: job {base_run.get('slurm_job_id')}  {base_run.get('base_url')}")
    print(f"variant : job {var_run.get('slurm_job_id')}  {var_run.get('base_url')}")
    print()
    header = (f"{'think':>5} {'conc':>4} {'TTFT p50':>16} {'TPOT p50':>16} "
              f"{'e2e p50':>16} {'req/s':>16}")
    print(header)
    print("-" * len(header))
    for key in sorted(base, key=lambda k: (k[0], k[1])):
        a, b = base[key], var.get(key)
        if not b:
            continue
        cells = []
        for field in ("ttft_p50_ms", "tpot_p50_ms", "e2e_p50_ms", "req_per_s"):
            cells.append(f"{fmt(a[field])}→{fmt(b[field])} {pct(b[field], a[field])}")
        print(f"{key[0]:>5} {key[1]:>4} " + " ".join(f"{c:>16}" for c in cells))


if __name__ == "__main__":
    main()
