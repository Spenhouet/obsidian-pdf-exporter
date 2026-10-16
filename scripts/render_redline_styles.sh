#!/usr/bin/env bash
# Render the redline scenario vault with every style: render_redline_styles.sh VAULT OUTDIR [styles]
set -euo pipefail
VAULT=$1; OUT=$2; STYLES=${3:-"a b c d e"}
REPO=$(cd "$(dirname "$0")/.." && pwd)
mkdir -p "$OUT"
cd "$VAULT"
for s in $STYLES; do
  uv run --project "$REPO" ope redline Handbook --from-commit v1.0 --to-commit v2.0 \
    -o "$OUT/redline-$s.pdf" -O redline.style=$s ${EXTRA:-} >/dev/null
  echo "style $s -> $OUT/redline-$s.pdf"
done
