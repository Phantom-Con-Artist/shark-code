# CLI-agent integration direction

Status: researched integration design, not implemented. The installed Codex, Claude, Antigravity and Muse binaries were detected; authentication was not inspected and no model call was made.

Shark should own the UI, task/event records, workspace versions, proposal review and application. A provider-neutral adapter owns each agent's process/transport and session identity. ADK remains one runtime option, rather than wrapping every other agent's reasoning loop inside ADK.

```mermaid
flowchart LR
  UI[Shark desktop] --> Task[Shared task service]
  Task --> ADK[ADK adapter]
  Task --> Codex[Codex app-server adapter]
  Task --> Claude[Claude CLI adapter]
  Task --> Others[Other supported adapters]
  Codex --> Tools[Agent-only MCP workspace tools]
  Claude --> Tools
  Tools --> Graph[Graphify and bounded source retrieval]
  Task --> Review[Versioned multi-file proposal]
```

The adapter contract needs discovery, supported-model catalog, authentication status, start, resume/send, events, interrupt/cancel and close. Store the provider's session/thread ID with the Shark task. Translate events into text deltas, completed messages, tool activity, approval requests, usage and final/error states. Cap outputs and avoid raw stdout/ANSI scraping when a structured protocol exists.

First implementation: Codex app-server, which is explicitly designed for persistent conversations, event streaming and approval handling in a product-owned UI. Second: Claude Code's supported programmatic interface, with streamed JSON and session resumption. Native CLI authentication and supported model selection should be preserved; do not extract credential files or treat consumer sign-in as a generic API key. Authentication behavior must be verified for the exact selected invocation mode (for example Claude's bare mode uses API/provider credentials rather than subscription login).

Expose the existing bounded exploration/impact/proposal operations through an actual MCP adapter. The current Shark JSON-lines protocol is not MCP. Graphify remains agent-only infrastructure; no human graph explorer is added.

CLI agents can own their built-in write/shell tools. Prefer an isolated worktree or controlled workspace copy, then import its diff through Shark's version-checked multi-file proposal engine. A worktree is not a process sandbox. Review/permissions must be enforced at the applicable provider and host boundaries; prompt instructions alone cannot guarantee that all CLI writes use Shark's tools.

Antigravity and Muse require individual structured-protocol and lifecycle checks; binary presence alone does not establish integration support. An embedded PTY can be a terminal fallback, but it does not automatically provide structured approvals, changes or task events.

Sources checked November 6, 2026: [Codex app-server](https://learn.chatgpt.com/docs/app-server), [Codex as a platform](https://developers.openai.com/blog/codex-as-a-platform), [Claude Code programmatic usage](https://code.claude.com/docs/en/headless), [Claude CLI reference](https://code.claude.com/docs/en/cli-reference).
