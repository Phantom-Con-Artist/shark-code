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

## Why

Coding agents are good at writing code and bad at telling you what they did. Most run in a terminal, edit your files directly, and leave you to work out the result from a scrolling log.

Shark Code puts the agent in the middle of an editor. You see each step as it happens, every edit comes back as a reviewable change, and the files on disk stay untouched until you apply it. The agent can be any CLI you already use, or an API key, and the UI works the same for all of them.

## How a run works

1. You ask Shark something in the chat, optionally attaching files or picking a mode.
2. Shark copies your project to a private folder and gives the engine a short map of the relevant code from its code graph.
3. The engine works in that copy. Its thinking, tool calls and messages stream into the chat.
4. When it finishes, Shark compares the copy with your project and turns the differences into a proposal: a list of created, edited and deleted files with inline diffs.
5. You review and apply, or discard. Applying checks that the files have not changed since the run started.

Read-only modes (Adversarial review, Planner, Explain) never produce a proposal. Any edits the engine makes in its copy are thrown away.

## Engines

| Engine | Kind | Setup |
| --- | --- | --- |
| Claude Code | CLI | `claude` installed and signed in |
| Codex | CLI | `codex` installed and signed in |
| Antigravity | CLI | `agy` installed and signed in |
| Muse | CLI | `muse` installed and signed in |
| OpenRouter | API key | Key in Settings, or `OPENROUTER_API_KEY` |
| Anthropic | API key | Key in Settings, or `ANTHROPIC_API_KEY` |
| Gemini | API key | Key in Settings, or `GEMINI_API_KEY` |

Shark finds installed CLIs on your `PATH` and in common install folders. Pick the engine, model and effort level from the model button in the chat box, or type `/model`, `/effort` or `/engine`. Slash commands from Claude Code (`.claude/commands`) and Codex (`~/.codex/prompts`) also show up under `/`.

You can run the same request on several engines at once from the mode menu ("Also run on"). Each result opens as its own tab.

## Features

**Chat**
- Modes: Builder, Debugger, Adversarial review, Planner, Explain, Test writer, Refactor. Each mode sends the engine a fixed brief.
- Skills change how Shark writes (concise, teacher, senior, caveman), and you can add your own.
- Step timeline with live status. Subagent steps nest under the step that started them.
- A run timer while working, and the total time when done.
- Context fill, prompt cache use, compaction and provider retries shown next to the chat box and in the thread.
- Clear errors for quota, rate limits, sign-in, network and full context, each with a next step.

**Code intelligence**
- Code graph built from your source, used to give engines relevant code before they start.
- Blast radius: see what depends on a file before you or the agent change it.
- CLI engines get Shark's tools live through an MCP server: graph search, impact, text search, outlines, git status and page checks.

**Editor**
- Monaco with tabs, breadcrumbs and a command palette.
- Built-in TypeScript, JavaScript, JSON, CSS and HTML support.
- Language servers for Python (pyright), Rust (rust-analyzer), Go (gopls) and C/C++ (clangd), when installed.
- Markdown opens rendered. HTML opens side by side with a live preview.
- Shark view puts the chat in the middle. Code view puts the editor in the middle with Shark docked on the right.

**Browser**
- Preview the project's HTML files or a local dev server.
- Pick any element on the page to find the source lines that render it, then ask Shark to change it.
- Console errors are collected and can be sent to Shark.
- Headless checks with Playwright report console errors and failed requests.

**Git**
- Explorer colours for modified, added, untracked, deleted and conflicted files.
- Stage, unstage, commit, switch and create branches, fetch, pull (fast-forward only) and push.
- Shark can draft a commit message from the staged diff.

**Workspace**
- Terminal, Problems panel, build and test tasks detected from the project, and dependency lists.
- Developer tools are detected and offered as tasks: ripgrep, ast-grep, Semgrep, difftastic, scc, ctags, gh, lazygit, delta.
- Profiles keep settings, keys and layout separate.
- Plugins: ask Shark to build a sidebar panel; manage them in the plugin manager.
- Light and dark themes, a high-contrast option, adjustable text size and reduced motion.

| Empty state | Light theme |
| --- | --- |
| ![Empty state](docs/screenshots/empty-state.png) | ![Light theme](docs/screenshots/conversation-light.png) |

## Status

Alpha. It works day to day on Linux, but expect rough edges and breaking changes. macOS and Windows builds have not been tested yet. See [NEXT-SESSION.md](NEXT-SESSION.md) for what is still open.

## Run from source

Needs Node 20+, Rust (stable), [uv](https://docs.astral.sh/uv/) and Python 3.12.

```sh
npm install
npm run backend:setup     # Python runtime + Rust core
npm run tauri dev
```

Optional, for page checks:

```sh
uv run --project backend playwright install chromium
```

Optional tools Shark uses when present: ripgrep, ast-grep, Semgrep, difftastic, scc, ctags, gh, lazygit, delta, pyright, rust-analyzer, gopls, clangd.

## Keyboard

| Keys | Action |
| --- | --- |
| `Ctrl K` | Command palette |
| `Ctrl P` | Go to file |
| `Ctrl L` | Focus the chat |
| `Ctrl Shift M` | Switch Shark / Code view |
| `Ctrl B` | Toggle sidebar |
| `Ctrl J` | Toggle terminal |
| `Ctrl S` | Save |
| `Ctrl Shift V` | Markdown preview |

On macOS use `Cmd` instead of `Ctrl`.

## Build a release

```sh
npm run package
```

This builds the Rust core and a single-file Python runtime (PyInstaller) into `src-tauri/binaries/`, then runs `tauri build` with them bundled.

## Tests

```sh
npm run backend:test      # Python runtime
cargo test                # Rust core
npx tsc --noEmit          # frontend types
```

`scripts/engine-playground.py` runs real engines against a small project with a known bug and checks that a correct fix comes back for review. It uses your CLI logins and quota.

## How it is built

| Part | Path | Role |
| --- | --- | --- |
| UI | `src/` | React 19, Monaco, xterm.js |
| Desktop shell | `src-tauri/` | Tauri 2: window, terminal, starts the runtime |
| Runtime | `backend/shark_runtime/` | Python: tasks, engines, code graph, git, language servers, browser, MCP |
| Core | `crates/` | Rust: confined file access, search, outlines, versioned multi-file edits with recovery |

The UI talks to the Python runtime over JSON lines. The runtime uses the Rust core for every read and write, so edits are version-checked and can be reverted. Task history lives in `.shark/` inside your project, which Shark keeps out of git status.

More detail: [docs/backend](docs/backend/README.md).

## Troubleshooting

- **"Required: [...]; optional: [...]" error:** the runtime is older than the app. Use Help → Restart Shark Backend.
- **Window reloads when a run starts (dev only):** restart `npm run tauri dev` so Vite picks up its watch settings.
- **An engine shows as not found:** check that its CLI runs in a terminal and is signed in, then reopen the engine picker.

## License

[Apache 2.0](LICENSE)
