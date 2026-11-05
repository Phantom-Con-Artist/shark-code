---
name: Shark Code workbench
description: Agent-first desktop coding workspace; the Shark conversation is the centre of every state
colors:
  bg: "#111113"          # Radix Slate 1: chrome, rail, sidebar
  canvas: "#18191b"      # Slate 2: chat and editor
  composer: "#1d1e21"
  raised: "#212225"      # Slate 3
  line: "#232528"
  line-strong: "#363a3f" # Slate 6
  text: "#edeef0"        # Slate 12
  text-2: "#b0b4ba"      # Slate 11
  accent: "#0bd8b6"      # Radix Teal 11 (text/icons on dark)
  accent-fill: "#12a594" # Teal 9
  ok: "#3dd68c"
  warn: "#ffca16"
  danger: "#ff9592"
typography:
  ui: "Geist Variable, 13px"
  code: "Geist Mono Variable"
rounded: { sm: "5px", base: "7px", lg: "11px", composer: "pill/16px" }
motion:
  ease: "cubic-bezier(0.16, 1, 0.3, 1)"
  durations: "120ms / 200ms / 300ms entrances"
---

## Overview

Shark is the product; engines (Claude Code, Codex, agy, Muse, OpenRouter, Anthropic, Gemini) are interchangeable behind it. The conversation is the default view and stays visible in every state. **Code view** puts the editor in the centre with Shark docked full-height on the right, for people who want to write code themselves. Desktop only.

## Colors

Radix Slate 12-step neutrals with Radix Teal as the only accent, in plain hex so WebKitGTK and Chromium match. Light and dark themes plus a high-contrast option, all in `src/App.css` tokens. Status always pairs colour with text or an icon. Git colours follow VS Code conventions: modified amber, added/untracked green, deleted red, conflict red with "!".

## Typography

Geist for UI and prose, Geist Mono for code and literal identifiers. Interface text is 13px, adjustable. Metadata never below 11px.

## Layout

Custom title bar (menus, back/forward, omni search, Shark/Code switch, window controls), activity rail, resizable sidebar (Sessions, Explorer, Search, Source Control, Run, Browser, plugins), centre (Shark or editor), optional bottom panel (Terminal, Problems), status bar (backend, branch, problems, agents working, cache, profile, engine). Every pane width persists per profile.

## Depth

Flat persistent surfaces separated by hairlines. Only popovers, dialogs and the composer float, with one shared shadow token. No glass, glow or decorative gradients.

## Components

- **Composer:** centred and rounded in the empty state; context chips, attachments, `/` commands (engine-native, model, effort, modes), mode chip, context group (compaction badge, prompt-cache state, fill ring) and the model picker.
- **Thread:** thinking blocks, a step timeline (spinner then check), subagent steps nested under their parent, lifecycle markers (context compacted, provider retrying), error callouts by category (quota, rate limit, auth, context, network), and a proposal card with inline diffs and created-file previews.
- **Browser:** project or localhost preview with an element picker. A pick shows the source lines that likely render it and drafts a change for Shark. Console errors stream in; Check runs headless Chromium.
- **Editor:** Monaco with built-in TS/JS/JSON/CSS/HTML services, plus language servers for Python, Rust, Go and C/C++ through the runtime. Markdown opens rendered; HTML opens side by side, with "Pick elements". Blast radius sits in the breadcrumb bar.

## Motion

Motion explains state changes: steps entering, a check popping in when a step finishes, the Shark "wake" while working, the compaction rule fading in. `prefers-reduced-motion` and the in-app setting remove all of it.

## Do's and Don'ts

Say "Shark", not the engine, except in the engine picker. Never invent test results or hide missing data. Show cost, cache and context limits honestly, and say when a number is unknown rather than guessing. Do not add marketing, oversized logos or decorative chrome.
