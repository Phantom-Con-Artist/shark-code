<div align="center">

<img src="public/brand/icon-256.png" width="72" alt="Shark Code" />

# Shark Code

A desktop code editor built around an agent. Use Claude Code, Codex, Antigravity, Muse or your own API key, review every change, then apply it.

[![Status: Alpha](https://img.shields.io/badge/status-alpha%20(in%20development)-orange)](#status)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)
![Tauri 2](https://img.shields.io/badge/Tauri-2-24C8DB?logo=tauri&logoColor=white)
![React 19](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=black)
![Rust](https://img.shields.io/badge/Rust-core-000000?logo=rust)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)

</div>

![Shark conversation](docs/screenshots/conversation-dark.png)

## What it does

- **One agent, many engines.** Pick a CLI you are already signed in to (Claude Code, Codex, Antigravity `agy`, Muse) or an API key (OpenRouter, Anthropic, Gemini). They all work the same way in the UI.
- **Review before apply.** CLI engines work in a private copy of your project. Their edits come back as a proposal with inline diffs. Nothing touches your files until you apply it.
- **Modes.** Builder, Debugger, Adversarial review, Planner, Explain, Test writer, Refactor. Read-only modes cannot change files.
- **Code intelligence for agents and you.** Code graph, blast radius, search and outlines. CLI engines get them live through Shark's MCP server.
- **Editor.** Monaco with language servers for Python, Rust, Go and C/C++, plus built-in TS/JS/HTML/CSS/JSON. Markdown and HTML preview.
- **Browser.** Preview your page, click any element to find the code that renders it, and send console errors to Shark. Headless checks run with Playwright.
- **Git.** Status colours, stage, commit, branches, fetch, pull and push.
- **Run state.** Context use, prompt cache, compaction, retries, quota and rate limits are shown in the chat.
- **Profiles, plugins, light and dark themes.**

| Empty state | Light theme |
| --- | --- |
| ![Empty state](docs/screenshots/empty-state.png) | ![Light theme](docs/screenshots/conversation-light.png) |

## Status

Alpha. It works day to day on Linux, but expect rough edges and breaking changes. See [NEXT-SESSION.md](NEXT-SESSION.md) for what is still open.

## Run from source

Needs Node 20+, Rust (stable), [uv](https://docs.astral.sh/uv/) and Python 3.12.

```sh
npm install
npm run backend:setup     # Python runtime + Rust core
npm run tauri dev
```

Optional tools Shark detects and uses: ripgrep, ast-grep, Semgrep, difftastic, scc, ctags, gh, lazygit, delta, pyright, rust-analyzer, gopls, clangd. Install Playwright's browser for page checks:

```sh
uv run --project backend playwright install chromium
```

## Build a release

```sh
npm run package           # builds the sidecars, then the Tauri bundle
```

## Tests

```sh
npm run backend:test      # Python runtime
cargo test                # Rust core
npx tsc --noEmit          # frontend types
```

## Layout

| Path | What |
| --- | --- |
| `src/` | React UI (workbench, editor, chat, browser, git) |
| `src-tauri/` | Desktop shell, window, terminal, runtime gateway |
| `backend/shark_runtime/` | Python runtime: tasks, engines, graph, git, LSP, browser, MCP |
| `crates/` | Rust core: file reads, search, outlines, versioned edits |
| `docs/` | Backend and design notes |

## License

[Apache 2.0](LICENSE)
