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

# Keep Chromium beside Playwright so the packaged runtime never downloads on first use.
export PLAYWRIGHT_BROWSERS_PATH=0
uv run --project backend --locked python -m playwright install chromium
uv run --project backend --no-sync python -m shark_runtime.selfcheck --require-browser

GRAMMAR_ARGS=()
for grammar in tree_sitter_python tree_sitter_typescript tree_sitter_javascript tree_sitter_rust tree_sitter_go tree_sitter_java tree_sitter_c tree_sitter_cpp tree_sitter_c_sharp tree_sitter_ruby tree_sitter_kotlin tree_sitter_php tree_sitter_scala tree_sitter_lua tree_sitter_bash tree_sitter_zig; do
  GRAMMAR_ARGS+=(--collect-all "$grammar")
done

INTEL_ARGS=()
for pkg in ast_grep_py sqlglot radon vulture dulwich rapidfuzz docstring_parser; do
  INTEL_ARGS+=(--collect-all "$pkg")
done

BUILD_KEY="$(python3 scripts/runtime-build-key.py)"
BUILD="$PWD/target/shark-runtime-build/$BUILD_KEY"
mkdir -p "$BUILD"
uv run --project backend --with pyinstaller==6.22.3 pyinstaller --noconfirm --onefile --name shark-runtime \
  --distpath "$BUILD/dist" --workpath "$BUILD/work" --specpath "$BUILD" \
  --paths backend "${GRAMMAR_ARGS[@]}" "${INTEL_ARGS[@]}" --collect-all playwright \
  --collect-all google.adk --collect-all google.genai --collect-all litellm \
  --collect-all nbformat --collect-all jupyter_client --collect-all ipykernel --collect-all IPython \
  --collect-all debugpy --collect-all jedi --collect-all parso \
  --collect-all jupyter_core --collect-all zmq --copy-metadata ipykernel --copy-metadata ipython \
  --collect-submodules mcp.server --collect-submodules mcp.shared --collect-submodules mcp.types --collect-data mcp --exclude-module mcp.cli \
  --collect-submodules shark_runtime --collect-data graphify --copy-metadata graphifyy \
  --hidden-import tiktoken_ext.openai_public --hidden-import tiktoken_ext \
  backend/shark_runtime/frozen.py
uv run --project backend --no-sync --with pyinstaller==6.22.3 python scripts/verify-bundled-code.py "$BUILD/dist/shark-runtime$EXT"
env -u PLAYWRIGHT_BROWSERS_PATH "$BUILD/dist/shark-runtime$EXT" --core-self-check --require-browser
python3 scripts/verify-notebook-runtime.py "$BUILD/dist/shark-runtime$EXT" "src-tauri/binaries/shark-backend-$TRIPLE$EXT"
cp "$BUILD/dist/shark-runtime$EXT" "src-tauri/binaries/shark-runtime-$TRIPLE$EXT"
echo "Sidecars ready for $TRIPLE:"
ls -lh src-tauri/binaries
