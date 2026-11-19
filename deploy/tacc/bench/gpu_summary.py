"""Summarise an `nvidia-smi dmon -o DT` log.

The question this answers: during decode, is the GPU compute-bound (SM busy) or
bandwidth/memory-bound (memory pipe busy, SM idle)? That decides whether
quantisation or kernel work can help at all.

  python3 deploy/tacc/bench/gpu_summary.py gpu-12345.csv [--from HH:MM] [--to HH:MM]
"""

import argparse
import statistics


def parse(path):
    rows = []
    header = None
    for line in open(path, errors="replace"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            # dmon prints two header comments; only the one naming the columns counts.
            if "gpu" in line:
                header = line.lstrip("#").split()
            continue
        if header is None:
            continue
        parts = line.split()
        if len(parts) < len(header) - 1:
            continue
        # -o DT gives "#Date Time ..." so a row starts with date + time
        stamp = None
        if len(parts[0]) in (8, 10) and ":" in parts[1]:
            stamp = parts[1]
            parts = parts[2:]
            keys = header[2:]
        else:
            keys = header
        if not stamp:
            continue
        rec = dict(zip(keys, parts))
        rec["time"] = stamp[:8]
        rows.append(rec)
    return rows


def num(rec, key):
    try:
        return float(rec.get(key, "nan"))
    except ValueError:
        return float("nan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--from", dest="t0")
    ap.add_argument("--to", dest="t1")
    args = ap.parse_args()

    rows = parse(args.path)
    if args.t0:
        rows = [r for r in rows if r["time"] >= args.t0]
    if args.t1:
        rows = [r for r in rows if r["time"] <= args.t1]
    if not rows:
        raise SystemExit("no samples in range")

    gpus = sorted({r.get("gpu") for r in rows})
    print(f"samples {len(rows)}  gpus {gpus}  window {rows[0]['time']}–{rows[-1]['time']}")
    print(f"{'gpu':>3} {'sm%':>6} {'mem%':>6} {'pwr W':>7} {'mclk':>6} {'pclk':>6} {'fb MB':>7}")
    for g in gpus:
        sub = [r for r in rows if r.get("gpu") == g]
        sm = [num(r, "sm") for r in sub]
        mem = [num(r, "mem") for r in sub]
        pwr = [num(r, "pwr") for r in sub]
        mclk = [num(r, "mclk") for r in sub]
        pclk = [num(r, "pclk") for r in sub]
        fb = [num(r, "fb") for r in sub]
        print(f"{g:>3} {statistics.mean(sm):>6.1f} {statistics.mean(mem):>6.1f} "
              f"{statistics.mean(pwr):>7.1f} {statistics.mean(mclk):>6.0f} "
              f"{statistics.mean(pclk):>6.0f} {statistics.mean(fb):>7.0f}")
        print(f"    max: sm {max(sm):.0f}%  mem {max(mem):.0f}%  pwr {max(pwr):.0f} W")

    busy = [num(r, "sm") for r in rows if num(r, "sm") > 5]
    idle = [num(r, "sm") for r in rows if num(r, "sm") <= 5]
    print(f"\nsamples with sm>5%: {len(busy)}/{len(rows)}  "
          f"mean sm {statistics.mean(busy):.1f}%" if busy else "\nnever busy")
    print(f"samples with sm<=5%: {len(idle)}/{len(rows)}")


if __name__ == "__main__":
    main()
