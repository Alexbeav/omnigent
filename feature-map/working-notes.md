# Working notes

Cline and other ACP chats collapse ordinary work narration into expandable Working notes. The final text run becomes visible when the turn settles. This changes presentation only; history and model input retain the original messages.

## Sub-features

- `live-notes`: narration stays collapsed while the assistant works and can be expanded at any time.
- `final-reply`: the final text run stays visible after completion; earlier notes remain collapsed.
- `restoration`: reloading a settled conversation restores collapsed notes and a visible reply.
- `actionable-cards`: structured questions, approvals, errors and tool activity retain their usual controls.
- `scoped-notes`: each pane uses its own harness and turn status.

## How to get to it (user POV)

- Main chat: open a Cline or other ACP conversation with assistant narration, tool activity and a final reply. Expand Working notes to inspect earlier text.
- Split pane: open the same conversation beside another provider and expand its notes independently.
- Mobile web: open the conversation on a narrow screen; the same disclosure and final reply remain available.

## Driving it with the repro environment

Preconditions: build this checkout's SPA and use its existing browser-test dependencies. The browser-contract lane needs no model credentials or running provider.

Run `tests/browser_ui/chat/test_transcript_rendering.py::test_acp_working_notes_keep_the_final_reply_visible` with recording enabled. Its main, split and mobile variants verify collapsed notes, expansion, the visible reply, unchanged history through the mocked REST endpoint and reload. Component coverage in `web/src/components/blocks/BlockRenderer.test.tsx` exercises streaming completion, continued turns, approvals and interrupted errors.

## Gotchas

- Ordinary ACP text has no reliable final-answer marker. The last contiguous text run is the visible reply after settlement; a provider that mixes narration into that same run cannot be separated safely by this display rule.
- While working, text is expandable rather than displayed as a streaming answer. Tools and actionable cards stay accessible.
- Native reasoning events retain their existing reasoning disclosure. Ordinary notes are not relabelled as private reasoning.
- Other harnesses retain their existing transcript presentation.
- Browser fixtures verify rendering and client boundaries, not a live model's output classification. Native mobile apps and Electron-specific behavior are outside this web change.
