# Primary platform chat panes

This first version shows one primary chat and up to two secondary chats on desktop. Each secondary pane owns its transcript stream, composer, and scroll container. Mobile hides secondary panes and keeps the primary chat.

## User paths

Use `Add pane…` in the primary header as the keyboard and screen-reader path. Drag a sidebar session to the marked left or right edge of a pane to place it on that side. Drag an already-open session to move it without creating a duplicate. Use the external-link button in a pane header to open that session in a separate browser window.

The `panes` URL query stores the two secondary session IDs. The optional `paneOrder` query stores their visual order, including a secondary chat to the left of the primary. The primary route and its state stay fixed when its position changes. Duplicate IDs and the primary session ID are removed. The layout caps the result at three total chats.

## Design evidence

The screenshot target shows three tall chat columns with a composer at the bottom of each column. This patch follows that column structure but uses Omnigent components and tokens.

VS Code uses editor groups for side-by-side work. Its documented paths include edge drag, split commands, resizable groups, and a separate window action. The implementation copies these interaction ideas only. It does not embed VS Code or copy its layout code.

References:

- [VS Code custom layout](https://code.visualstudio.com/docs/configure/custom-layout)
- [VS Code editor group commands](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/browser/parts/editor/editorCommands.ts)

## Tested evidence

Run these commands from the repository root:

```sh
pnpm --dir web run type-check
pnpm --dir web exec vitest run src/shell/ConversationPanes.test.tsx src/components/chat/SideChatPane.test.tsx
```

On 2026-10-16 (local time), frontend lint, type checking, and the final production build passed.
The follow-up checks passed 585 store tests, 361 composer tests and 192 other pane/shell/bubble component tests.

The three isolated Chromium journeys in `tests/browser_ui/chat/test_conversation_panes.py` and `test_pane_session_controls.py` passed in 10.84 seconds.
They verify each pane's model, reasoning, permission and queue controls, including busy-stream/idle-sidebar disagreement.
It opened one pane through the header add control and another through sidebar drop. A left drop placed a secondary before the primary, and a right drop placed another after it.
It showed three columns at 1600 by 900 pixels, separate drafts, and a send routed only to its secondary session.
Keyboard and pointer resizing both changed the selected pane.
At 390 by 844 pixels, the secondary panes were hidden.
The sidebar showed a working child with a direct link.

Local screenshots and recordings are under `.omnigent/verify/`. The final browser result is `final-pane-browser.xml`.
The primary header stays inside the primary column so its controls cannot cover secondary-pane controls.
Read-only shared sessions show their transcript without a send composer.

## Human verification

1. Open a session on a desktop viewport at least 1024 pixels wide.
2. Choose two different sessions with `Add pane…`. Make sure that three columns appear.
3. Type a different unsent draft in each composer. Scroll each transcript to a different position. Make sure that neither action changes another pane.
4. Drag each divider. Make sure that the secondary column changes width and the other chats remain usable.
5. Drag a sidebar session to the left edge of the primary pane, then another to its right edge. Make sure that the visual order matches each drop, the primary route and draft stay fixed, and reload keeps the order. Drag an open chat to reposition it without a duplicate.
6. Use only the keyboard to choose `Add pane…`, close a pane, and open a pane in a new window.
7. Resize below 768 pixels. Make sure that only the primary chat is visible.
8. In a secondary pane, choose another model and reasoning level from its model pill.
   Make sure that the primary chat keeps its model and draft.
9. Drag a primary or secondary header to the marked right edge and release it.
   Make sure that a new window opens for that chat.
10. Start another header drag, press Escape, and release the mouse.
    Make sure that no window opens. Repeat with a sidebar row.
11. While a secondary chat is working, type a follow-up and press Enter.
    Make sure that it appears in that pane's queue and waits for the current turn.
    Edit or remove a queued message, or use its send-now arrow to steer the active turn.
    Ctrl+Enter (Command+Enter on macOS) sends that pane's whole queue immediately with the default shortcut setting.
    Make sure that the primary draft and queue stay unchanged.

## Limits and unproven behavior

Pane headers and sidebar rows can request popouts through the marked 48-pixel right edge.
Headers share pointer capture, Escape cancellation, and capture-loss handling.
Releases beyond the viewport also request a popout when the browser delivers the event.
The Chromium test delivers a release 20 pixels outside the viewport through Playwright.
That proves browser event handling, not a real OS desktop drop.
The explicit popout button remains available, and pane widths do not persist after reload.

The shared `SessionHarnessPicker.tsx` supplies ordinary panes with their own model and effort menus.
Permission, Plan mode and host controls also target that pane's session.
Pending fork side chats keep their simpler composer until they have a session.
Native model changes retain the main composer's confirmation behavior.
Ordinary panes also share the queue strip and the queue/Always steer and keyboard preferences.
Each queue flush uses that conversation's live status, including when the sidebar still shows idle.

Browser references: [pointer capture](https://developer.mozilla.org/en-US/docs/Web/API/Element/setPointerCapture)
and [popup activation](https://html.spec.whatwg.org/multipage/interaction.html#tracking-user-activation).
