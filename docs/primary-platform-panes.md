# Primary platform chat panes

This first version shows one primary chat and up to two secondary chats on desktop. Each secondary pane owns its transcript stream, composer, and scroll container. Mobile hides secondary panes and keeps the primary chat.

## User paths

Use the `Add pane…` select at the bottom-right of the chat area as the keyboard and screen-reader path. You can also drag a session row from the sidebar to the marked chat edge. Use the external-link button in a pane header to open that session in a separate browser window.

The `panes` URL query stores the two secondary session IDs. Duplicate IDs and the primary session ID are removed. The layout caps the result at three total chats.

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

On 2026-10-15, frontend lint, type checking, and the production build passed.
The resumed component run passed 178 tests across AppShell, the pane container, and SideChatPane.

The isolated browser test `tests/browser_ui/chat/test_conversation_panes.py` passed.
It opened one pane through the add control and another through sidebar edge-drop.
It showed three columns at 1600 by 900 pixels, separate drafts, and a send routed only to its secondary session.
Keyboard and pointer resizing both changed the selected pane.
At 390 by 844 pixels, the secondary panes were hidden.
The sidebar showed a working child with a direct link.

Local screenshots and recordings are under `.omnigent/verify/pane-evidence/`.
The primary header stays inside the primary column so its controls cannot cover secondary-pane controls.
Read-only shared sessions show their transcript without a send composer.

## Human verification

1. Open a session on a desktop viewport at least 1024 pixels wide.
2. Choose two different sessions with `Add pane…`. Make sure that three columns appear.
3. Type a different unsent draft in each composer. Scroll each transcript to a different position. Make sure that neither action changes another pane.
4. Drag each divider. Make sure that the secondary column changes width and the other chats remain usable.
5. Drag a sidebar session to the marked chat edge. Make sure that it opens once and does not replace the primary chat.
6. Use only the keyboard to choose `Add pane…`, close a pane, and open a pane in a new window.
7. Resize below 768 pixels. Make sure that only the primary chat is visible.

## Limits and unproven behavior

The browser does not provide a reliable cross-window drag contract, so this version uses an explicit popout button. Dragging a pane outside the browser does not create a window. Pane widths do not persist after reload. The isolated browser drive also opened a new browsing context with no opener, then closed and reopened a pane without losing its draft. Browser policy still determines final window placement.
