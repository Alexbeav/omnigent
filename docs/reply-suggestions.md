# Suggested next replies

This optional feature proposes the user's next message after a live assistant turn
finishes. It supports full chat and every ordinary split or rail pane in native
Codex and native Claude sessions. It is separate from question forms and approvals.
The feature defaults to off; deployment and account activation are separate steps.

## Use and configuration

Open **Settings → General → Composer → Suggest my next reply**. The choice is saved
for the current Omnigent account in this browser, including across reloads. No
provider, main-chat model, or global agent setting changes.

With the setting on, leave the active chat's entire composer empty and keep its
window focused. After a new assistant turn completes, a faint proposed reply can
appear. **Tab** or **Right Arrow** copies it into an editable draft. It never sends
a message. Typing or Escape dismisses it for that turn. Existing drafts, files,
quotes, mentions, queued messages, completion menus, and input-method composition
retain precedence. New chats, historical turns loaded on entry, native temporary
forks, terminal views, hidden/inactive panes, read-only sessions, outstanding async
questions, approvals, compaction, and busy sessions do not start generation.
Changing focus while a request is pending cancels it; the same turn is not retried.

One eligible completion starts at most one background request after 750 ms of idle
time. This adds usage on the session's existing account; it is not the free Codex
desktop Predictions beta. No new inference service or credential store is used.
If the current account does not advertise a supported economy model, the feature
quietly leaves the composer usable. It never substitutes a costly model or another
provider. Unsupported runners return no suggestion.

## Generation, isolation, and limits

The server validates edit permission, idle state, the exact completed response,
recent context, and pending question metadata before dispatch and before displaying
a result. A bounded cache shares pending/completed work across browser requests.
The browser caches dismissal by session/turn and drops late results after edits,
permission changes, disablement, cancellation, or another turn. Every ordinary pane
uses the same hook and its own conversation state.

Only the latest four user/assistant messages enter the prompt, each clipped to
1,200 characters, with a total ceiling of 6,000 characters. Older question metadata
is inspected for unresolved questions but is not sent to the model. Full histories,
tools, files, workspace contents, and the main agent's instructions are not included.
There is no cross-turn prompt-cache guarantee: the bounded prompt changes per turn.
Each request uses an ephemeral native process, a temporary empty working directory,
no tools, and the session's own resolved provider/account configuration, including
ordinary child-agent sessions. Unresolved session/child specs fail closed.

- **Codex:** select an advertised model from the economy-model registry in
  `omnigent/models/model_fallbacks.py`. Launch an ephemeral read-only `codex exec`
  with replacement instructions, MCP/apps/plugins/tools disabled, no rules or
  workspace discovery. Custom providers receive zero request/stream retries through
  the existing provider helper. Reserved built-in providers keep their own retry
  behavior because Codex rejects retry overrides under those IDs. The selected
  provider/account is unchanged. The installed CLI does **not**
  expose a verified hard output-token ceiling for this path. The 40-word prompt
  instruction and 300-character display filter are not token limits.
- **Claude:** select an advertised Haiku model from that session's launch catalog.
  Reuse its resolved launch config, not a title generator's account fallback.
  Print mode uses `--safe-mode`, an empty tool list and MCP config, no settings
  sources/hooks, no session persistence, one turn, and no retries or model fallback.
  `CLAUDE_CODE_MAX_OUTPUT_TOKENS=256` is verified on the installed CLI's HTTP request
  as `max_tokens: 256`; the provider still determines actual token accounting.

Process execution has a 12-second timeout, with a 17-second overall runner deadline
and a 20-second browser/server deadline. Explicit cancellation kills the process
group. Omnigent starts one generation process and never retries it or switches
models/providers. Codex built-in internal retries can occur within the process
until the deadline or cancellation. The output filter accepts at most 300
characters and treats `NONE` as no suggestion. These controls bound context, time,
and display length; Codex token cost remains uncapped by a native token parameter.

## Transport and usage

`POST /v1/sessions/{id}/next-reply` requires edit access and JSON
`{ "enabled": true, "source_response_id": "…", "request_id": "…" }`.
`DELETE /v1/sessions/{id}/next-reply/{request_id}` cancels pending work, including a
cancel arriving before its POST finishes validation. Neither route appends a chat
message or resumes a session. The runner receives trusted session metadata and the
bounded transcript through existing authenticated runner routing.

Reported usage is stored additively in per-turn `omnigent.reply_usage.*` labels,
separate from native cumulative usage so the next native update cannot overwrite
it. `GET /v1/sessions/{id}/next-reply/usage` returns totals and per-model buckets.
Reported usage is retained even when output is discarded or a killed process
emits it; unreported usage cannot be reconstructed. Main-chat dollar totals do not
include a fabricated estimate for these requests. The in-memory single-flight
cache assumes one routing owner; multi-owner routing would need a shared ledger.

## Verification and compatibility

Component tests cover LAN HTTP UUID fallback, unanswered async-question metadata,
IME/completion precedence, drafts, permissions, visibility, stale results,
dismissal, and unsupported harnesses. Browser journeys cover both native harnesses,
full chat and three simultaneous panes, editable acceptance, no sends, and draft
races. Transport tests cover authorization, caching, cancellation, usage and account
isolation. See `tests/browser_ui/chat/test_reply_suggestions.py`,
`tests/server/test_reply_suggestions.py`, `tests/runner/test_reply_suggestions.py`,
and `web/src/hooks/useReplySuggestion.test.tsx`.

Local wire probes with synthetic credentials and a loopback provider confirmed
empty tool arrays for both installed CLIs and Claude's 256-token request parameter.
They do not prove live-provider entitlement or latency. No recurring production
generation or production setting activation was performed during implementation.
The question branch adds typed `async_user_input` / `async_question_reply` message
fields and `asyncUserInput` / `asyncQuestionReply` transcript blocks. Both gates
consume these fields structurally on this branch; integration must preserve their
hydration and source-item correlation, including cancelled replies. Outstanding
questions must remain ineligible even when no elicitation or `blockedOn` exists.
Combined server tests persist typed questions and replies in the real store.
They cover an unanswered question older than the initial history page, and confirm
that an answer or dismissal releases the generation gate.

Primary CLI references: [Claude environment variables](https://code.claude.com/docs/en/env-vars),
[Claude CLI flags](https://code.claude.com/docs/en/cli-reference), and
[Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).
Earlier provider comparison and native-prediction blockers are recorded in
[the investigation](primary-platform-prompt-suggestions.md).
