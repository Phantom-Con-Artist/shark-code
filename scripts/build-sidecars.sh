#!/usr/bin/env bash
# Build the release sidecars the packaged app ships with:
#   src-tauri/binaries/shark-backend-<triple>   Rust workspace core
#   src-tauri/binaries/shark-runtime-<triple>   Python runtime + MCP server (PyInstaller, one file)
# Then: npm run tauri build -- --config src-tauri/tauri.bundle.conf.json
set -euo pipefail
cd "$(dirname "$0")/.."
TRIPLE="$(rustc -vV | sed -n 's/^host: //p')"
EXT=""; [[ "$TRIPLE" == *windows* ]] && EXT=".exe"
mkdir -p src-tauri/binaries

cargo build --release --bin shark-backend
cp "target/release/shark-backend$EXT" "src-tauri/binaries/shark-backend-$TRIPLE$EXT"

BUILD="$(mktemp -d)"
trap 'rm -rf -- "$BUILD"' EXIT
uv run --project backend --with pyinstaller pyinstaller --noconfirm --clean --onefile --name shark-runtime \
  --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD" \
  --paths backend \
  --collect-all google.adk --collect-all google.genai --collect-all litellm \
  --collect-submodules mcp.server --collect-submodules mcp.shared --collect-submodules mcp.types --collect-data mcp --exclude-module mcp.cli \
  --collect-submodules shark_runtime --collect-data graphify \
  --hidden-import tiktoken_ext.openai_public --hidden-import tiktoken_ext \
  backend/shark_runtime/frozen.py
cp "$BUILD/dist/shark-runtime$EXT" "src-tauri/binaries/shark-runtime-$TRIPLE$EXT"
echo "Sidecars ready for $TRIPLE:"
ls -lh src-tauri/binaries
