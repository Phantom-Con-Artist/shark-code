---
name: Shark Code workbench
description: Compact conversation-led desktop coding workspace
colors:
  ground: "#151517"
  sidebar: "#19191b"
  surface: "#1d1d20"
  raised: "#27272b"
  border: "#323237"
  control: "#73737d"
  text: "#ececee"
  muted: "#b1b1ba"
  accent: "#9bcbb6"
typography:
  body:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "13px"
    lineHeight: 1.65
  welcome:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "26px"
    fontWeight: 500
    lineHeight: 1.3
rounded:
  control: "4px"
  composer: "8px"
spacing:
  small: "8px"
  medium: "16px"
components:
  button-primary:
    backgroundColor: "#e9e9ed"
    textColor: "#18181a"
    height: "34px"
    rounded: "5px"
---

## Overview

An operating interface for long desktop coding sessions. Conversation leads; files, source and review remain alongside it. Compact spacing is user-confirmed. Comfortable spacing, larger text, Verdana, higher contrast and reduced motion are persistent preferences. Desktop is the current scope.

## Colors

Neutral charcoal surfaces separate panes by lightness and thin rules. Mint signals status and focus. Primary actions use neutral light-on-dark inversion. Color never substitutes for a status label.

## Typography

Platform sans for interface/prose, system monospace for source and literal identifiers. Default interface text is 13px, adjustable to 15/17px. Metadata is at least 11px. Conversation prose uses generous line height; comfortable mode increases its measure. Avoid eyebrows above headings.

## Layout

40px title bar, 46px activity rail, 224px explorer/task navigation, central conversation, adjacent source/review, optional terminal below and 25px status bar. Panes retain predictable positions. Focus mode hides secondary panes on request. Window resizing must preserve access; mobile/tablet refinement is out of scope.

## Elevation & Depth

Persistent surfaces are flat. Borders separate panes. Only dialogs float, with a subdued offset shadow; no glow, glass or decorative gradients.

## Shapes

Controls have modest 4–5px radii; composer 8px and dialogs 9px. Lucide icons and the existing Shark fin mark carry identity.

## Components

Files and Tasks switch the sidebar. Source and Review switch the adjacent pane. Composer stays available while the thread scrolls; no automatic history scrolling. Review starts with persisted What changes / What to check explanations, then files and impact, then optional Before/After snapshots. Missing explanations remain explicit. Graphify has no human-facing controls.

Keyboard focus is visible; dialogs trap/restore focus and close with Escape. Monaco supports screen readers and Tab focus navigation. Ctrl/Cmd+K or P finds files/actions, S saves, backtick toggles terminal, Shift+F toggles focus. Status changes use text, not animation.

## Do's and Don'ts

Keep the conversation-led layout, compact default and comfortable option. Explain native-only browser boundaries and missing data honestly. Retain evidence with task proposals. Do not reintroduce sample agent runs, fabricate test results, expose Graphify as a user explorer, or claim full WCAG conformance from automated checks.
