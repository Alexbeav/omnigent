# Structured questions

Native Codex asynchronous questions and the Omnigent `sys_ask_user` tool display selectable choices and custom answers below the original assistant text.
The user submits an ordinary message to the question's conversation.
The tool already acknowledged its request, so no approval request waits for this answer.
See the [transport and draft contract](../docs/codex-async-questions.md) for details.
Native Claude questions use the same form but return answers through their original hook.

## Sub-features

- `choices`: the first suggestion starts selected, but no answer sends before Submit.
- `custom-and-multiple`: custom text works for every question, including requests with several questions or repeated titles.
- `scoped-reply`: full chat and all three split panes send replies to the source chat after focus changes.
- `restoration`: card drafts survive remount and reload in the same tab, and confirmed answers restore from history.
- `retry-and-cancel`: failed or unconfirmed replies retry with the same ID, and Cancel sends no selected answer.
- `composer-preservation`: card submission leaves ordinary composer drafts and restored retry state intact on success and failure.
- `tool-fallback`: Cline's ACP connection exposes `sys_ask_user` through the existing Omnigent tool relay.
- `native-claude`: native hook choices and custom text return to the source chat without sending an ordinary message.

## How to get to it (user POV)

Open a native Codex chat that receives an asynchronous structured question, or ask
an agent such as Cline to use `sys_ask_user` with two questions.
Select a choice or type a custom answer, then use Next for additional questions and Submit for the complete reply.
Use Cancel to dismiss the questions without selecting an answer.
The same controls appear when the chat occupies a split pane.
Add two chats through Add chat pane to exercise the three-pane path.
For native Claude, ask it to use `AskUserQuestion` with two questions, select or
type each answer, then Submit. Cancel declines that native question request.

## Driving it with the repro environment

Preconditions: build the web SPA and install this checkout's test dependencies.
The browser-contract lane needs no model credentials, native session, or running Omnigent server.

Run `tests/browser_ui/chat/test_async_questions.py` with recording enabled.
The asynchronous variants disable `crypto.subtle` to cover the LAN HTTP browser boundary.
The full-chat variant receives the question through live SSE.
The three-pane variants restore all three questions from history and submit each pane's reply after focus moves to another composer.
Both restore a custom answer and ordinary draft after reload, double-click Submit, and reload the confirmed response.
Cline fallback variants cover full chat and a side pane. Native Claude variants
cover the full chat and each of three panes, returning selections and custom text
to the owning hook while preserving composer drafts.

Server validation, cancellation, pending and committed retry suppression, and the native user-message echo use
`tests/server/integration/test_sessions_endpoints.py::test_message_repeat_with_same_stable_id_forwards_once`.
Native source metadata uses `tests/harnesses/codex_native/forwarder/test_user_messages.py`.
Pending metadata restoration uses `tests/runtime/test_pending_inputs.py::test_delivery_identity_and_original_enqueue_time_survive_retry_and_restore`.
Web component and store tests cover failed submission, remount, cancellation, and preservation of restored ordinary drafts.
Tool registration and persisted question output use `tests/runner/test_ask_user_dispatch.py`;
the ACP relay is covered by `tests/inner/test_acp_executor.py`.
Claude's real hook entry point with a mocked HTTP server is covered by
`tests/harnesses/claude_native/test_claude_native_hook.py::test_ask_user_question_permission_transport`.

## Gotchas

- A suggested choice is not user authorization until Submit.
- Native blocking questions, Claude hooks, and MCP questions use their existing approval cards and response channels.
- Cline's ACP permission choices cannot carry a question answer; its fallback uses the Omnigent tool connection.
- A host update is required even when the web server already has the question controls. After moving a chat to an older host, request a fresh question only after upgrading its runtime.
- Plain prose, generic tool output, and old question messages without structured data do not gain controls.
- Browser fixtures prove the real renderer and HTTP/SSE client boundaries, but do not prove delivery to a live provider.
- A queued native Codex reply stays retryable until its user-message echo confirms delivery. The ACP fallback confirms the ordinary reply when the server persists it.
- Draft persistence depends on the browser tab's session storage, and pending correlation has the existing native index's process lifetime.
