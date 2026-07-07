#!/usr/bin/env bash
# Export HACKATHON architecture diagrams to PNG via @mermaid-js/mermaid-cli.
#
# Usage (from repo root):
#   bash scripts/export-mermaid-png.sh
#   bash scripts/export-mermaid-png.sh --svg   # also write SVG alongside PNG
#
# Requires Node.js 18+. Run `npm ci` once at repo root (pins mmdc + puppeteer).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

DIAGRAMS_DIR="docs/diagrams"
OUT_DIR="docs/images"
PUPPETEER_CONFIG="${DIAGRAMS_DIR}/puppeteer-config.json"

EXPORT_SVG=false
for arg in "$@"; do
  case "$arg" in
    --svg) EXPORT_SVG=true ;;
    -h|--help)
      echo "Usage: bash scripts/export-mermaid-png.sh [--svg]"
      echo ""
      echo "First time:"
      echo "  npm ci"
      echo "  bash scripts/export-mermaid-png.sh"
      exit 0
      ;;
  esac
done

if ! command -v node >/dev/null 2>&1; then
  echo "Node.js is required. Install Node 18+ and retry." >&2
  exit 1
fi

if [[ ! -x node_modules/.bin/mmdc ]]; then
  echo "Installing @mermaid-js/mermaid-cli..."
  if [[ -f package-lock.json ]]; then
    npm ci --ignore-scripts
  else
    npm install --ignore-scripts
  fi
fi

mkdir -p "$OUT_DIR"

# Prefer system Chrome when Puppeteer's bundled browser is missing (common on first run).
detect_chrome() {
  if [[ -n "${PUPPETEER_EXECUTABLE_PATH:-}" && -x "${PUPPETEER_EXECUTABLE_PATH}" ]]; then
    return 0
  fi
  local candidates=(
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    "/usr/bin/google-chrome"
    "/usr/bin/google-chrome-stable"
    "/usr/bin/chromium"
    "/usr/bin/chromium-browser"
  )
  for c in "${candidates[@]}"; do
    if [[ -x "$c" ]]; then
      export PUPPETEER_EXECUTABLE_PATH="$c"
      echo "Using browser: $c"
      return 0
    fi
  done
  return 1
}

if ! detect_chrome; then
  echo "No system Chrome found — installing headless shell via Puppeteer (one-time, ~150 MB)..."
  npx puppeteer browsers install chrome-headless-shell
fi

MMDC=(./node_modules/.bin/mmdc)

COMMON_FLAGS=(
  -b white
  -w 1920
  -H 1080
  -s 2
  -p "$PUPPETEER_CONFIG"
)

render() {
  local input="$1"
  local output="$2"
  local base="${output%.png}"
  echo "→ ${input} → ${output}"
  "${MMDC[@]}" -i "$input" -o "$output" "${COMMON_FLAGS[@]}"
  if [[ "$EXPORT_SVG" == true ]]; then
    "${MMDC[@]}" -i "$input" -o "${base}.svg" -b white -p "$PUPPETEER_CONFIG"
  fi
}

render "${DIAGRAMS_DIR}/system.mmd"         "${OUT_DIR}/architecture-system.png"
render "${DIAGRAMS_DIR}/sequence.mmd"       "${OUT_DIR}/architecture-sequence.png"
render "${DIAGRAMS_DIR}/trust-boundary.mmd" "${OUT_DIR}/architecture-trust-boundary.png"

echo ""
echo "Done. PNGs written to ${OUT_DIR}/"
ls -lh "${OUT_DIR}"/architecture-*.png
