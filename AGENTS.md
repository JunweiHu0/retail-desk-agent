# Project instructions

- The canonical project is `/home/mnyh/projects/retail-agent` in WSL.
- `main` and `v0.1.0-stable` preserve the initial stable demo. Make ongoing changes on `dev`.
- Focus on the desktop Web application. Mobile feature development is paused by user request.
- Do not print API keys, store them in tracked files, or copy the local `.env` into the Windows source mirror.
- Keep model credentials in the WSL `.env`. Never include credentials in frontend bundles or test reports.
- Ordinary automated tests must use the deterministic model or MockTransport. Live checks require user authorization and an isolated database.
- Reuse the upstream Retail tools and preserve the identity, ownership, explicit approval and audit boundaries.
