#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${LIGHTWEIGHT_CHARTS_VERSION:-4.2.0}"
TARGET="$ROOT/shared/vendor/lightweight-charts.standalone.production.js"
URL="https://unpkg.com/lightweight-charts@${VERSION}/dist/lightweight-charts.standalone.production.js"

echo "Downloading lightweight-charts@${VERSION} -> ${TARGET}"
curl -fsSL "$URL" -o "$TARGET"
echo "Done ($(wc -c < "$TARGET") bytes)"
