# Structured questions in chats

Native Codex can send `functions.request_user_input_async` as an assistant message with structured question data.
The tool acknowledges the request immediately, so there is no pending native approval request to resolve.
Omnigent retains the original message and displays the shared question form below it.

Agents can also call the framework-owned `sys_ask_user` tool through their existing
Omnigent tool connection. It accepts `questions` with a `title` and optional string
`options`, posts the same structured message to the calling conversation, and
acknowledges it only after the server confirms persistence. The agent can continue
independent work while answers arrive as ordinary user messages. No model-supplied
conversation, agent, or native request identity is accepted.

This is the question path for Cline over ACP. The installed Cline CLI 3.0.72 does
not register its SDK's native `ask_question` callback in its ACP adapter. Its
ACP adapter also ignores the per-session MCP server list. Configure its
[private MCP settings launch](AGENT_YAML_SPEC.md#custom-acp-agents) before testing
`sys_ask_user`: creating the relay alone does not establish that Cline loaded it.
The local runtime keeps that settings file scoped to the calling chat. Its
**Allow once**, **Allow always**, and **Reject** options remain permission
decisions. They are not repurposed as question answers. Native Claude Code keeps
its `AskUserQuestion` hook and returns selected or custom answers through the
original permission request's `updatedInput`; the question itself grants no
permission to execute another tool.

## Answers and drafts

Each question accepts a suggested choice or custom text.
A request can contain several questions, including questions with the same title.
The first suggested choice starts selected, but only an explicit Submit sends the answers.
Cancel sends an ordinary message that states that the user dismissed the questions without an answer.
Neither action grants a tool permission or interrupts the running turn.

Answers use the existing ordinary message path in the question's conversation, even after focus moves to another pane.
A running native turn receives the message through its existing steering path.
The card keeps its own draft through remounts and reloads in the same browser tab through the existing session draft storage.
It does not consume the ordinary composer's text, attachments, or restored retry state.
Session storage failures retain only the in-memory draft, as with ordinary composer drafts.

While delivery awaits the native user-message echo, the card shows a queued status and a Retry delivery button.
Retry retains the same answers and reply ID, including after reload.
A confirmed answer or cancellation restores from conversation history and removes the card's saved draft.
A delivery error stays on the card, and Retry delivery sends the same reply.

## Transport and correlation

The Codex forwarder accepts only structured native `agentMessage` data with `delivery: "async"` and a validated `questions` array.
It preserves the native item's `id` as `async_user_input.call_id` and the native source ID through the existing external-item path.
Message parsing persists the metadata, so history and the live item event carry the same data.
Malformed metadata leaves the original assistant text visible without controls.
There is no prose scraping or generic tool-name detection.

`sys_ask_user` reuses this message contract and the existing external-item endpoint.
Direct dispatch uses the trusted tool-call and response identities to deduplicate
replays. The managed ACP relay retains its existing MCP operation for transport
retries and assigns the question its own call identity. A new invocation creates
a new question, even with the same display text. A denied request or failed
persistence returns an error rather than claiming the questions were posted.

The persisted `async_user_input` contains `call_id`, `reply_id`, and `questions` with `title` and optional string-array `options`.
The server supplies `reply_id` as the first 32 hexadecimal characters of SHA-256 over `omnigent-async-question:{session_id}:{source_item_id}`.
The browser uses that ID directly, including on LAN HTTP where `crypto.subtle` is unavailable.
Question answer keys are `{call_id}:{zero_based_question_index}`.
The ordinary user message carries `async_question_reply` with `source_item_id`, string-valued `answers`, and `cancelled`.
The server validates the source conversation and complete answers, then creates the readable user text itself.

Replies share one deterministic ID per source message.
Session-affine dispatch serializes concurrent retries and returns the pending or committed reply without forwarding it twice.
After confirmation, a different reply receives a conflict response.
The existing native pending-input index carries the reply metadata until the transcript forwarder persists the user-message echo.
Its existing process-local lifetime and delivery recovery limits also apply here.
A server restart before the echo loses that pending correlation, so delivery across that boundary is not an exactly-once guarantee.

## Compatibility and checks

Native blocking `item/tool/requestUserInput`, native Claude hooks, and MCP elicitation keep their existing approval paths.
Generic tool output and ordinary assistant prose do not create these cards.
Previously stored plain-text questions have no structured metadata and do not gain controls retroactively.
The source Codex schema supports single choice plus custom text, not checkbox selection of several choices in one question.
The shared form retains checkbox support for the existing blocking paths.

The CLI and web server must both include the asynchronous message contract. The
server deployment from `dc94d2137` already includes it. Hosts still running
`38f30aa96` drop the new Codex metadata and do not expose `sys_ask_user`; moving a
chat onto such a host does not update its installed package. Upgrade that host's
runtime and restart its managed chats when idle. Previously saved plain messages
remain plain; request a fresh question after the restart.

See the [feature map](../feature-map/async-questions.md) for full chat, split-pane, reload, and retry checks.
Browser tests use the built SPA with isolated mocked HTTP/SSE contracts.
They prove browser routing and state, while server integration tests separately prove native echo correlation and retry suppression.
A separate isolated real-provider test persisted a fresh Codex async question,
sent a synthetic Markdown answer, and received the expected Codex acknowledgement.
Retrying that answer left one correlated user message. This establishes the native
round trip; it does not establish a human browser click through a live provider.
No existing pending user question is answered by these tests.

On 2026-10-17, Alex also completed a human two-question round trip in this Codex
chat after restarting Pegasus WSL onto source `225e7f7af`. Both selected answers
arrived together as a structured reply. This verifies live choice submission;
custom text and pane routing remain covered by the isolated browser journeys.

Alex subsequently confirmed Claude's multiple-choice form and completed a live
Cline two-question form after the private MCP launch fix. Cline received
**Green** and **Just confirm receipt** as an ordinary user reply and acknowledged
both choices. All three provider question paths now have human confirmation;
custom text and every pane position retain their separate automated coverage.

The NAS rollout on 2026-10-17 deployed source `910495755` and the generic
**Questions** heading. Six other reachable hosts received that source and the
process-local Cline MCP launch configuration, preserving their host identities
and silent startup. Automated Cline question/answer canaries passed on Eagle
Windows and Athena-Lpt. Eagle WSL, Pegasus Windows, Steam Deck and macbook still
return an unexplained Cline internal error before posting a question, despite
CLI 3.0.72. Their readiness report alone is not proof of question delivery.
Fleet debugging is paused; Rocky is offline and unchanged. See the
[current rollout boundary](primary-platform-plan.md#remaining-work-after-question-acceptance-2026-10-17)
before moving a working chat between hosts.
