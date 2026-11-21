# 2026-11-21 · formal test 40 × seed 0/1/2

Qwen3.8-27B, vLLM 0.26, thinking auto, 10 concurrent episodes, variant lg_b1.

Formal 600 s per-episode budget:

- seed 0: 31/40 (0.775)
- seed 1: 30/40 (0.750)
- seed 2: 30/40 (0.750)
- all: 91/120 (0.758)
- pass_3: 25/40 (0.625)

The 14 episodes that hit `wall_time_budget` were rerun at `max_seconds=1800`
(all other settings unchanged). 10 of 14 then matched the target DB; the
diagnostic, mixed-budget numbers are:

- seed 0: 34/40 (0.850)
- seed 1: 33/40 (0.825)
- seed 2: 34/40 (0.850)
- all: 101/120 (0.842)
- pass_3: 31/40 (0.775)

The remaining four rerun failures are task 36 seed 0 (variant selection plus
approval loop), task 100 seed 0/2 (action-card `after` preview makes the
simulated user reject, then transfer), and task 100 seed 1 (simulator exhausted
its 4096-token reasoning budget). None is a wall-time failure. See
`EVAL-VALIDITY.md` and `reruns/summary.json`.

Raw run JSON is in this directory; rerun JSON is under `reruns/`. The 14 rerun
sessions were also imported into the local replay database
(`/tmp/retail-eval-local.sqlite3`, owner `replay_viewer`) from their
`snapshot.json`; the merged matrix cells link directly to them. Open index.html
through `./deploy/run.sh docs`.

The portable replay export (`replay/`) and step-by-step instructions for
importing it and viewing the sessions in the frontend are in
[`REPLAY.md`](REPLAY.md).
