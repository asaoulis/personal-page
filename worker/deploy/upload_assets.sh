#!/usr/bin/env bash
# Build + upload the public release assets the GitHub Actions inference worker
# downloads on cache miss. USER-AUTHORIZED public publication (2026-07-11):
# checkpoint + fiducial DB are deliberately public release assets.
# Requires an authenticated `gh` CLI (gh auth login).
#
#   bash worker/deploy/upload_assets.sh   # build + upload (clobbers existing)
#
# Assets land on release tag `assets-v1` of asaoulis/personal-page.
# Runner-side layout after extraction (see the workflow): /home/runner/fnet_assets/
#   japan10s/fiducial/...      the fiducial Instaseis DB (QA forward model)
#   japan_v1/{model_meta.json, checkpoints/best_model-*.ckpt}
#   config/{first_ml_npe_japan_ci.yaml, fnet_demo_stations.txt, components.json}
#   win32tools/...             NIED WIN32->SAC converters (x86 binaries + source)

set -euo pipefail

TAG="assets-v1"
SEISMO=/home/alex/work/seismo-sbi
DB_PARENT=/data/alex/axisem_dbs
CKPT_DIR=$SEISMO/ml-checkpoints/japan_v1/japan_v1
CFG_DIR=$SEISMO/scripts/configs/japan
STAGE=$(mktemp -d /data/alex/tmp_assets_stage.XXXX)   # big files: stage on the data disk
trap 'rm -rf "$STAGE"' EXIT

echo "== staging under $STAGE"
mkdir -p "$STAGE/japan_v1/checkpoints" "$STAGE/config"

# 1. Fiducial DB (~950 MB) -> japan10s/fiducial/...
tar czf "$STAGE/japan10s_fiducial.tar.gz" -C "$DB_PARENT" japan10s/fiducial

# 2. Checkpoint: ONLY the best (most negative val_loss) ckpt + meta + metrics.
BEST=$(ls "$CKPT_DIR"/checkpoints/best_model-val_loss=*.ckpt | sort -t= -k2 -g | head -1)
echo "  best checkpoint: $BEST"
cp "$BEST" "$STAGE/japan_v1/checkpoints/"
cp "$CKPT_DIR/model_meta.json" "$STAGE/japan_v1/" || {
    echo "ERROR: no model_meta.json — regenerate via npe_backend.ensure_model_meta first"; exit 1; }
cp "$CKPT_DIR/metrics.csv" "$STAGE/japan_v1/" 2>/dev/null || true
tar czf "$STAGE/japan_v1_ckpt.tar.gz" -C "$STAGE" japan_v1

# 3. CI-adapted config: textual path rewrite (keeps anchors/comments intact).
sed -e "s|/data/alex/axisem_dbs/japan10s|/home/runner/fnet_assets/japan10s|g" \
    -e "s|$CFG_DIR|/home/runner/fnet_assets/config|g" \
    -e "s|/data/alex/fnet_japan|/home/runner/fnet_assets/fnet_japan|g" \
    "$CFG_DIR/first_ml_npe_japan.yaml" > "$STAGE/config/first_ml_npe_japan_ci.yaml"
cp "$CFG_DIR/fnet_demo_stations.txt" "$CFG_DIR/components.json" "$STAGE/config/"
if grep -n "/data/alex\|/home/alex" "$STAGE/config/first_ml_npe_japan_ci.yaml"; then
    echo "ERROR: unrewritten local paths remain in the CI config (lines above)"; exit 1
fi
tar czf "$STAGE/ci_config.tar.gz" -C "$STAGE" config

# 4. WIN32 tools (x86 binaries + C source).
cp "$SEISMO/scripts/win32tools.tar.gz" "$STAGE/win32tools.tar.gz"

# 5. Create-or-update the release and upload (clobber = refresh in place).
cd /home/alex/work/personal-page
if ! gh release view "$TAG" >/dev/null 2>&1; then
    gh release create "$TAG" --title "Inference worker assets" \
        --notes "Model checkpoint, fiducial Instaseis DB, CI config and WIN32 tools for the live F-net inference workflow. Managed by worker/deploy/upload_assets.sh."
fi
gh release upload "$TAG" \
    "$STAGE/japan10s_fiducial.tar.gz" \
    "$STAGE/japan_v1_ckpt.tar.gz" \
    "$STAGE/ci_config.tar.gz" \
    "$STAGE/win32tools.tar.gz" \
    --clobber

echo "== done: https://github.com/asaoulis/personal-page/releases/tag/$TAG"
