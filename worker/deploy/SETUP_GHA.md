# One-time GitHub Actions setup (live F-net inference)

Two user actions are required; everything else is automated.

## 1. Add the NIED credentials as repo secrets

Fill in `worker/deploy/gha_secrets.env.template` (copy the two values from your
locked `worker/.env`), then use **one** of:

**Method A — gh CLI** (from the personal-page repo root; installs: `sudo apt install gh`,
then `gh auth login`):

```bash
gh secret set -f worker/deploy/gha_secrets.env.template
# verify:
gh secret list          # should show FNET_USERNAME, FNET_PASSWORD
```

**Method B — web UI**: GitHub → `asaoulis/personal-page` → Settings →
Secrets and variables → Actions → "New repository secret". Create
`FNET_USERNAME` and `FNET_PASSWORD` with the values from `worker/.env`.

Afterwards **delete the filled-in template copy** (`git checkout` it or wipe the
values). Never commit real values.

## 2. Upload the model/DB assets as a public release

The runner needs four private-to-this-machine artefacts, published as **release
assets** on `personal-page` (public, per decision 2026-07-11; release assets live
outside the git tree — zero repo bloat, no LFS quota):

- `japan10s_fiducial.tar.gz` — the ~950 MB fiducial Instaseis DB (QA forward model)
- `japan_v1_ckpt.tar.gz` — the trained NPE checkpoint + `model_meta.json`
- `ci_config.tar.gz` — the japan YAML (paths rewritten for the runner) + stations + components
- `win32tools.tar.gz` — NIED WIN32→SAC converters (x86 binaries + source)

Build + upload everything with:

```bash
bash worker/deploy/upload_assets.sh          # needs gh auth (Method A above)
```

Re-run with `--clobber` after the final checkpoint lands to refresh the model:

```bash
bash worker/deploy/upload_assets.sh --clobber
```

## Notes

- The Actions workflow caches all assets (`actions/cache`), so the release is
  only downloaded on cache miss (~monthly), not every 30-min tick.
- Cron is best-effort (runs can be late/skipped) — the state machine is
  resumable, so this only delays publication, never loses events.
- Rotating the NIED password later: update the two secrets (Method A or B); no
  code change.
