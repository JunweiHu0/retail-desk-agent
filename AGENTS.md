# Retail Desk project instructions

Read `/data1/han/AGENTS.md` and `/data1/han/Line/AGENTS.md` first in this workspace.
The user is Xhan. Work on `feat/retail-agent-eval`.

- Keep this repository focused on application code, tests, the DB evaluator and TACC deployment.
- Follow the parent workspace execution rules. Keep research notes, experiment outputs and non-TACC deployment tooling outside this repository.
- Preserve the main browser contract: HttpOnly cookie authentication, account-owned sessions/orders, message SSE and decision JSON.
- B1 is the native baseline; lg_* variants use StateGraph. Keep the default B1 until an improvement is demonstrated.
- Use official Retail write functions. Preview is not execution; only the approval endpoint commits.
- Browser sessions share account data; evaluator episodes have isolated DBs. Targets never enter model inputs.
- Pin tau2 to `0c69df456a96aa76a1162591574dad9c427a34d7`. Never overwrite frozen inputs or historical results.
- Current model diagnostics are limited to tasks 41 and 47; do not launch full cohorts by default.
- Do not change frontend UI, push branches, expose credentials, or replace live serving without explicit task scope.
