"""Shark modes and skills: strict briefs every engine receives, enforced by the host.

A mode decides what the run may do. Read-only modes never produce a proposal: CLI engines run in
their read-only/plan permission mode and any edits they make to the disposable copy are discarded;
API engines do not receive the propose tool. Skills only change how Shark communicates.
"""
from __future__ import annotations

import re

MODES = {
    "chat": {"label": "Chat", "read_only": False, "brief": (
        "MODE: CHAT. This is a normal open conversation, not a structured engineering task. Respond naturally to "
        "whatever is asked: questions, brainstorming, writing, quick snippets, or casual talk. Do only what is "
        "asked; do not assume a build/review/plan structure, and do not read or edit files unless the request "
        "needs it or asks for it.")},
    "builder": {"label": "Builder", "read_only": False, "brief": (
        "MODE: BUILDER. Implement the request end to end. Read the relevant code first, follow the project's existing "
        "patterns, keep the change as small as the goal allows, and handle edge cases. Finish with what changed, why, "
        "and how to verify it. Never claim tests ran unless you ran them.")},
    "debugger": {"label": "Debugger", "read_only": False, "brief": (
        "MODE: DEBUGGER. Work strictly in this order: 1) restate the symptom; 2) find where it originates by reading code "
        "and evidence; 3) state the root cause with file:line references; 4) apply the minimal fix for the root cause, "
        "not the symptom; 5) suggest a regression test. Do not refactor or change unrelated code.")},
    "review": {"label": "Adversarial review", "read_only": True, "brief": (
        "MODE: ADVERSARIAL REVIEW. You are a hostile reviewer. Do NOT modify any file. Hunt for real defects: logic "
        "errors, unhandled edge cases, race conditions, security issues, data loss, broken contracts and missing tests. "
        "Report each finding as: severity (critical/high/medium/low), file:line, the concrete failing scenario, and the "
        "fix. Order by severity. If you find nothing material, say so plainly instead of inventing issues.")},
    "planner": {"label": "Planner", "read_only": True, "brief": (
        "MODE: PLANNER. Do NOT modify any file. Investigate the code and produce an implementation plan: numbered steps "
        "naming the files to change, risks and unknowns, and how to verify each step.")},
    "explain": {"label": "Explain", "read_only": True, "brief": (
        "MODE: EXPLAIN. Do NOT modify any file. Explain how the relevant code works, tracing the real control and data "
        "flow with file:line references. Prefer concrete walkthroughs over generalities.")},
    "tests": {"label": "Test writer", "read_only": False, "brief": (
        "MODE: TEST WRITER. Only create or edit test files; never change application source. Cover the main path, edge "
        "cases and failure modes using the project's existing test framework and conventions.")},
    "refactor": {"label": "Refactor", "read_only": False, "brief": (
        "MODE: REFACTOR. Improve structure without changing behaviour. Keep public interfaces stable, change in small "
        "safe steps, and state why behaviour is preserved.")},
}

SKILLS = {
    "caveman": "STYLE: Talk like a caveman. Short blunt sentences, small words, drop filler and articles. Code stays correct and normal.",
    "concise": "STYLE: Be terse. No preamble or recap. Bullet points over paragraphs.",
    "teacher": "STYLE: Teach as you go. Explain the why behind each step in plain language for a newer developer.",
    "senior": "STYLE: Act as a senior engineer. Call out trade-offs, risks and maintainability concerns directly.",
}


def compose(goal: str, mode: str = "builder", skills=(), custom=()) -> str:
    """Wrap a goal in the mode brief and skills; validated, bounded, deterministic."""
    spec = MODES.get(mode or "builder")
    if spec is None:
        raise ValueError(mode)
    parts = [spec["brief"]]
    parts += [SKILLS[s] for s in skills if s in SKILLS]
    parts += ["STYLE (user skill): " + re.sub(r"\s+", " ", c)[:600] for c in custom if isinstance(c, str) and c.strip()][:5]
    return "\n".join(parts) + ("\n\nMESSAGE:\n" if mode == "chat" else "\n\nTASK:\n") + goal


ERROR_PATTERNS = [
    ("context", r"context (length|window)|too many tokens|maximum context|prompt is too long|token limit|input is too long"),
    ("quota", r"quota|usage limit|insufficient (credits|balance|quota)|\b402\b|billing|credit balance|limit reached|out of credits|spend limit"),
    ("rate_limit", r"rate.?limit|\b429\b|too many requests|overloaded|resource.?exhausted"),
    ("auth", r"\b401\b|\b403\b|unauthori[sz]ed|authentication|not logged in|log ?in|api key|invalid key|permission denied|forbidden"),
    ("network", r"connection|timed? ?out|network|dns|unreachable|ssl|econn"),
]


def classify(message: str) -> str:
    text = (message or "").lower()
    for category, pattern in ERROR_PATTERNS:
        if re.search(pattern, text):
            return category
    return "other"
