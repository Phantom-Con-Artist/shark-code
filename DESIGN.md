# Shark Code workspace

The primary surface is an operating interface for long coding sessions. Conversation owns the center of the workspace; code and proposed changes sit beside it. The agent plan, activity, and review handoff stay in the conversation. The user selected this conversation-led direction.

## Visual system

Neutral dark surfaces continue the existing editor's identity. Elevation uses changes in lightness. Thin rules separate persistent panes; contained plans use a slightly raised surface. Mint indicates completed steps and additions; muted rose indicates removed code. Controls and navigation remain neutral.

| Role | Token | Value |
| --- | --- | --- |
| Canvas | `--ground` | `#151517` |
| Navigation | `--sidebar` | `#18181a` |
| Surface | `--surface` | `#1d1d20` |
| Raised surface | `--raised` | `#252528` |
| Separator | `--border` | `#2c2c30` |
| Primary text | `--text` | `#e7e7e9` |
| Secondary text | `--muted` | `#a0a0a7` |
| Metadata | `--faint` | `#9999a3` |
| Completed / added | `--accent` | `#9bcbb6` |
| Removed code | `--red` | `#d9a2a6` |

Use the platform Arial/Helvetica sans stack for controls and prose, and the system monospace stack for code, paths, and measurements. Conversation prose is 13px with generous line height. Dense labels are 11–12px. The Shark fin is the product mark, rendered as a simple flat vector. Lucide supplies the remaining icons.

## Layout and interaction

Desktop uses a 232px navigation column, a flexible conversation pane, and a code pane occupying 42% of the remaining space. The composer remains visible while the thread scrolls. The review action remains below the independently scrolling diff. At initial widths of 1000px or less, code starts collapsed. Below 760px, navigation becomes a menu and code opens as an overlay. The header toggle always controls code visibility.

Interactive controls have visible keyboard focus, and dialogs trap focus, close with Escape, and restore focus to their trigger. Ctrl/Cmd+K opens search, Ctrl/Cmd+N creates a session, and Ctrl/Cmd+comma opens preferences. Enter sends; Shift+Enter adds a line. Reduced motion disables smooth scrolling and transitions.

## Prototype boundary

Reviews start with what changes, why it helps, and the affected file. Code is optional, shown as readable Before/After versions with syntax highlighting instead of large red/green blocks.

The sample session and proposal are illustrative fixtures. Runs advance through a local timer, can pause and resume, and preserve independent per-session approval state. Files contains a collapsible folder tree and a locally bundled Monaco editor. Browser workspace files persist in localStorage. Opening a folder uses the browser File System Access API where available; native workspace commands provide local filesystem access in Tauri. Saves check for external edits before writing. The terminal is a limited workspace console in the browser and an interactive PTY shell in the desktop app. Accepting the sample records a local approval without writing files. Ask mode explains the runtime connection boundary. Reloading resets conversations, while saved browser workspace files persist. Do not imply that a model or native keychain is connected until those integrations exist. Label the browser console separately from the desktop system shell.
