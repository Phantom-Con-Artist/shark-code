# Desktop accessibility verification

Shark targets WCAG 2.2 AA and incorporates cognitive-accessibility patterns. This is an implementation target, not a conformance certification. Current design scope is desktop; the user excluded mobile and tablet refinement.

Implemented controls:

- Compact spacing by default, with persistent comfortable spacing and 13/15/17px interface text.
- A persistent Verdana reading option, higher contrast, and reduced motion.
- User-controlled focus mode, stable pane positions, readable conversation spacing, concise labels and optional code/evidence disclosures.
- Visible focus, named controls, composer/source skip links, keyboard shortcuts, dialog focus trapping/restoration and Escape dismissal.
- Monaco screen-reader support and Tab focus mode, plus xterm's screen-reader mode.
- Plain text status alongside color; no simulated task runs, automatic history scrolling, pulsing progress indicators or default blinking cursor.
- Native-only actions explain their availability and recover without pretending a run occurred.

## Checks performed

Chromium browser checks used axe-core 4.10.3 with WCAG A/AA tags (`wcag2a`, `wcag2aa`, `wcag21aa`, `wcag22aa`). The desktop workspace and Settings at comfortable spacing/17px text had **zero automatically detected violations**. Some desktop editor/contrast checks were marked incomplete by axe and still require manual assessment. Automated checks do not cover every WCAG requirement or every agent conversation state.

Keyboard/browser interaction checks verified: settings focus entry, dialog Tab trapping, preference persistence after reload, focus-mode pane hiding, native-only action feedback, actual Monaco keyboard input and saving to browser storage, and opening the terminal. Browser console logs had no runtime exceptions in this run. The user later narrowed the scope to desktop; early phone/tablet captures are retained only as development artifacts and are not a design commitment.

Backend checks cover real ADK orchestration with an offline scripted model, Graphify extraction and dependency evidence, persisted task/review history and cancellation, stale-analysis rejection, desktop-to-runtime dispatch and native file/PTY behavior. Live provider execution, a full native-window interaction run, screen-reader walkthroughs and representative ADHD/dyslexia user testing remain unverified.

## Further assessment

Manually inspect reading order and announcements with supported screen readers; verify browser/webview zoom and OS text scaling, native terminal keyboard escape behavior and contrast in varied source languages; assess long task histories, long proposals and provider error states; and gather feedback from users with differing reading and attention needs. Cognitive preferences vary, so no font or spacing setting is described as universally suitable.

Sources: [WCAG 2.2](https://www.w3.org/TR/WCAG22/) and the [reference study](design-references.md).
