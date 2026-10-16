# Primary platform chat panes

Desktop shows up to three equal chat panes. Each pane owns its transcript stream, composer, and scroll container. A shared toolbar above the columns follows the selected chat. Mobile shows the selected chat.

## User paths

Use `Add pane…` in the primary header as the keyboard and screen-reader path. Drag a sidebar session over the left or right half of a pane to place it on that side. The hovered half shows a blurred preview with a blue outline and a Split view label. Drag an already-open session to move it without creating a duplicate. Use the external-link button in a pane header to open that session in a separate browser window.

The route identifies the selected chat. The `panes` URL query stores the other session IDs, and `paneOrder` stores all visual positions. Reordering does not change the selection. Duplicate IDs are removed, and the layout caps the result at three total chats.

## Active pane

Click inside a chat or focus its controls to make that pane active.
A blue outline marks the active pane when multiple chats are open.
Click another session in the sidebar to replace only the active chat.
The other chats keep their positions, drafts and scroll state.
Divider widths stay with their positions when a chat is replaced.
Every gap between adjacent chats has a resize divider, including when the primary chat is in the middle or on the right.
Drag a divider, or focus it and press Left/Right, to resize only its two neighbors.
Each chat keeps a minimum width of 320 pixels.
Click an already-open session in the sidebar to focus its existing pane.

Selecting any pane updates the route and shared toolbar without remounting the other chat surfaces.
Share, session menus, agent information, Terminal, and Workspace actions target the selected session.
A terminal view belongs to its pane, and switching back to Chat restores its composer.
Model, reasoning, permission, host, queue, and steering controls remain in each composer.
Use Load earlier messages to read more history in a pane. New responses do not force the scroll to the bottom while you read older messages.

File links resolve against the chat that contains them, including inactive panes
with different workspaces. Right-click a file or website link to open it in
Omnigent, open it in a browser, or copy its destination. File destinations preserve
their source chat and any cited line or column. Web clients open a new tab in the
current browser; the desktop app can open the system's default browser.
Website navigation inside Omnigent requires the desktop app's browser support.

Starting a chat replaces only the selected slot. This applies to the project New session button and menu, sidebar New session, command palette, and new-session shortcut.
Other chats retain their drafts, scroll positions, and divider widths.
If you select another pane while creation runs, completion fills the original slot and retains your selection.
If creation fails, that slot restores the unsent prompt.
The temporary `new` layout ID is a blank composer, never a server session ID.
Mobile uses the ordinary single-chat navigation.
Control/Command-click and middle-click keep the normal browser tab behavior.
The keyboard Add pane control and explicit popout buttons remain available.

## Design evidence

The screenshot targets show tall chat columns with a composer at the bottom of each column, plus a large split preview during dragging. This patch follows that column structure but uses Omnigent components and tokens.

VS Code uses editor groups for side-by-side work. Its documented paths include edge drag, split commands, resizable groups, and a separate window action. The implementation copies these interaction ideas only. It does not embed VS Code or copy its layout code.

References:

- [VS Code custom layout](https://code.visualstudio.com/docs/configure/custom-layout)
- [VS Code editor group commands](https://github.com/microsoft/vscode/blob/main/src/vs/workbench/browser/parts/editor/editorCommands.ts)

## Tested evidence

The isolated Chromium journeys in `test_conversation_panes.py` and `test_pane_session_controls.py` cover these paths:

- Both split directions, reordering, cancellation, the three-chat limit, and explicit and outside-page popouts.
- Both resize dividers in all chat orders, with pointer and keyboard input.
- Sidebar replacement and selection without losing other drafts or slot widths.
- Share permissions, Workspace, and Terminal controls for the selected session.
- Project creation in the selected slot, foreground and background completion, and failed creation with draft recovery.
- Sidebar, shortcut, and command-palette new chats without collapsing the layout.
- Per-pane model, reasoning, permissions, queue, and steering, including a busy stream with an idle sidebar.
- A 390-pixel phone viewport after moving a chat into a resized slot.

Component and store tests also cover initial prompt delivery once, navigation under a rebased URL, inactive-pane history loading, and scroll anchoring.
Private logs and recordings are under `.omnigent/verify/active-pane-controls-20261016/`.
These browser tests use isolated session contracts. They do not send real provider prompts or prove an OS desktop drop.

Run these commands from the repository root:

```sh
pnpm --dir web run type-check
pnpm --dir web exec vitest run src/shell/ConversationPanes.test.tsx src/components/chat/SideChatPane.test.tsx src/lib/routing.test.tsx
```

## Human verification

1. Open a session on a desktop viewport at least 1024 pixels wide.
2. Choose two different sessions with `Add pane…`. Make sure that three columns appear.
3. Type a different unsent draft in each composer. Scroll each transcript to a different position. Make sure that neither action changes another pane.
4. Drag both dividers in each direction. Make sure that only the two adjacent columns change width.
   Move the primary chat to each of the three positions and repeat.
   Focus each divider and use Left/Right arrows to repeat with the keyboard.
5. Drag a sidebar session over the left half of the primary pane, then another over its right half. Make sure that the visual order matches each drop, the primary route and draft stay fixed, and reload keeps the order. Drag an open chat to reposition it without a duplicate.
6. Use only the keyboard to choose `Add pane…`, close a pane, and open a pane in a new window.
7. Select a different pane, then resize below 768 pixels. Make sure that only the selected chat is visible.
8. In a secondary pane, choose another model and reasoning level from its model pill.
   Make sure that the primary chat keeps its model and draft.
9. Drag a primary or secondary header beyond the page and release it.
   Make sure that a new window opens for that chat.
10. Start another header drag, press Escape, and release the mouse.
    Make sure that no window opens. Repeat with a sidebar row.
    Click inside one pane and choose a different sidebar chat.
    Make sure that only that pane changes and all divider positions stay fixed.
    Choose a chat that is already open and make sure that its pane becomes active without duplication.
11. While a secondary chat is working, type a follow-up and press Enter.
    Make sure that it appears in that pane's queue and waits for the current turn.
    Edit or remove a queued message, or use its send-now arrow to steer the active turn.
    Ctrl+Enter (Command+Enter on macOS) sends that pane's whole queue immediately with the default shortcut setting.
    Make sure that the primary draft and queue stay unchanged.

12. Select each pane and open Share, then Workspace. Make sure that each action belongs to the selected session.
    Open Terminal in a native session, then return to Chat. Make sure that the other composers stay visible.
13. Select the middle pane, then choose New session in a project. Send a prompt.
    Make sure that the new chat replaces only that slot and the other drafts and divider widths remain.
    Repeat with sidebar New session, the new-session shortcut, and the command palette.
14. Load earlier messages in a long chat. Read older content while another response arrives.
    Make sure that the pane keeps your reading position and other chats stay unchanged.

## Limits and unproven behavior

The separate right-edge popout indicator is removed. The right half of each chat belongs to its split target.
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
