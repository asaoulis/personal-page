#!/usr/bin/env bash
# Local live-monitor daemon — THE production host for the download-dependent tick.
#
# WHY LOCAL: GitHub-hosted runners authenticate to NIED fine but the win32 data
# service returns dataless archives to their (Azure) egress IPs — diagnosed
# 2026-07-11 (see worker/docs/UPDATE_GUIDE.md §5). The workstation's egress works,
# so the daemon runs here; the GHA workflow stays as a dispatchable no-download
# fallback (supersede/index bookkeeping + publish path).
#
# Usage:  bash worker/deploy/run_local_daemon.sh [store_dir]
#   - detaches with setsid+nohup (survives closing the terminal)
#   - one tick every $INTERVAL s; per-tick publish (force-push to the data branch)
#   - log: <store>/daemon.log ; stop: kill $(cat <store>/daemon.pid)
set -euo pipefail

STORE="${1:-/data/alex/fnet_live/store}"
INTERVAL="${FNET_INTERVAL:-1200}"
WORKER_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Publish credentials: GitBranchStore reads GITHUB_TOKEN + GITHUB_REPOSITORY.
GITHUB_TOKEN="$(gh config get -h github.com oauth_token 2>/dev/null || gh auth token 2>/dev/null)"
export GITHUB_TOKEN
export GITHUB_REPOSITORY="asaoulis/personal-page"

if [ -f "$STORE/daemon.pid" ] && kill -0 "$(cat "$STORE/daemon.pid")" 2>/dev/null; then
    echo "daemon already running (pid $(cat "$STORE/daemon.pid")) — not starting a second copy"
    exit 1
fi

cd "$WORKER_DIR"
setsid nohup conda run -n seismo-sbi python -m fnet_monitor.monitor \
    --loop --interval "$INTERVAL" --publish --out "$STORE" \
    >> "$STORE/daemon.log" 2>&1 &
echo $! > "$STORE/daemon.pid"
echo "live-monitor daemon started (pid $(cat "$STORE/daemon.pid"), interval ${INTERVAL}s, store $STORE)"
echo "log: $STORE/daemon.log"
