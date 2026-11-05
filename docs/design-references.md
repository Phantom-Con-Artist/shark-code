# Workspace reference study

Reviewed the actual interface images on November 6, 2026, before UI implementation. Reference images are research material and are not shipped in the app.

| Reference | Observation | Shark adaptation |
| --- | --- | --- |
| [VS Code user interface](https://code.visualstudio.com/docs/editing/getting-started/userinterface), annotated workspace screenshot | Stable activity rail, explorer, editor tabs, bottom terminal, concise status bar | Predictable locations for files, editing and terminal; collapsible explorer; label controls and expose shortcuts |
| [Cursor 3 agent tabs](https://cursor.com/changelog/3-0), official agent-tabs screenshot | Conversation and source share a workbench; tool activity is grouped; composer stays in reach | Conversation in the center, source/review alongside, concise activity disclosures, persistent composer |
| [Antigravity IDE](https://antigravity.google/product/antigravity-ide), official composer and artifact images | Task-oriented agent input and artifacts provide a review surface | Agents use Graphify internally; users see a task’s understandable impact summary and proposal; readable review comes before detailed source |

The user selected compact editor-style spacing, with a comfortable alternative. Use a neutral dark palette and Shark's existing fin/mint identity. Avoid the references' decorative glow, large red/green diff blocks and multiple competing chat columns. Panel changes are user initiated.

Accessibility decisions draw on [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [clear page structure](https://www.w3.org/WAI/WCAG2/supplemental/patterns/o2p03-page-structure/), [manageable content](https://www.w3.org/WAI/WCAG2/supplemental/patterns/o5p03-manageable-quantity/) and [white spacing](https://www.w3.org/WAI/WCAG2/supplemental/patterns/o3p10-whitespace/). Implement keyboard navigation and visible focus, sufficient text contrast, explicit state labels, adjustable spacing/text and focus mode. Cognitive-accessibility patterns supplement WCAG; they do not establish full conformance or universal suitability for every person.

Graphify is reserved for agent tools. The human workbench intentionally has no graph explorer or direct graph-query controls.
