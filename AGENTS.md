# Retail Desk workspace instructions

Read `/data1/han/AGENTS.md` and `/data1/han/Line/AGENTS.md` first when working locally. The user is Xhan. This repository is independent of HandTrack.

- Work on `feat/retail-agent-eval`, based on `deploy/tacc` at `a3173371079b53779a933e50ed79d528b7843a96`.
- Follow `docs/PLAN.md` and `docs/EVAL_PROTOCOL.md`. Update progress with evidence, not inferred success.
- Local work is for implementation, static checks, and small tests. Full suites, model serving and evaluation run through the existing `ssh huoshan` configuration.
- Do not stop existing GPU processes or modify shared environments/drivers. Use isolated directories under `/vePFS/han/retail-desk` remotely.
- Preserve upstream data and prior experiment outputs. Pin tau2 to `0c69df456a96aa76a1162591574dad9c427a34d7`.
- Baseline and enhanced agents share business tools, validation, approvals, initial information and evaluation budgets. Target DB and comparison scope must never enter agent inputs.
- Keep external validation at boundaries, use existing typed values internally, and avoid speculative abstractions or defensive infrastructure.
- Do not expose credentials, push to shared branches, or send messages to collaborators unless explicitly requested.
