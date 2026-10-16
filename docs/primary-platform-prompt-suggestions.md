# Suggested replies in chat composers

Status: a composer prototype is implemented on `feature/composer-prompt-suggestions`.
It is not connected to a suggestion source and is not deployed.
The generation preference is pending: reuse native suggestions only, or generate a fallback with a separate background model request.
No suggestion-generation request or provider configuration change ran during this investigation.

## Composer behavior

The shared composer accepts an optional suggestion identified by session and turn.
The suggestion appears as faint placeholder text only while the input is empty and writable.
Tab or Right Arrow copies it into the editable draft without sending it.
Typing or Escape dismisses it for that session and turn.
A new suggestion ID permits another suggestion, even when its text matches an earlier one.
Existing drafts, disabled input, read-only input, composition, modified keys, and completion handlers retain precedence.
No caller supplies the new property yet, so the installed single-chat, split-pane, and new-session behavior remains unchanged.

The prototype passes 43 shared-composer checks, plus frontend lint and type checking.
The tests distinguish the placeholder from the saved draft and confirm that acceptance updates the controlled draft state.
The verification logs are private under `.omnigent/verify/prompt-suggestions-20261016/`.
There is no browser or live-provider proof for an integrated suggestion flow yet.

## Provider interfaces inspected on 2026-10-16

Claude Code 2.1.301 documents prompt suggestions and exposes `prompt_suggestion` messages through print-mode stream JSON with `--prompt-suggestions`.
Its interactive terminal and print mode are different transport paths.
Omnigent's `claude-native` bridge currently mirrors an interactive session, so a print-mode event is not automatically available there.

The installed Codex CLI is 0.162.1.
Its generated experimental app-server schema exposes no next-prompt suggestion request or notification.
The Codex desktop app can therefore offer a UI feature that this installed integration cannot retrieve through its schema.
This observation does not establish that every Codex release or private client lacks such a path.

Omnigent already has isolated background inference for session titles through the selected harness.
That is a useful starting point for a generated fallback, with a distinct next-prompt task and response contract.
Do not silently ask the title endpoint for a title and present that output as a suggested reply.

Official references:

- [Claude Code prompt suggestions](https://code.claude.com/docs/en/interactive-mode#prompt-suggestions).
- [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server).

## Remaining integration work

After the generation preference is resolved, bind suggestions to completed assistant turns and the original session ID.
A generated fallback needs a bounded, tool-free background request using the existing provider authentication path.
It must not create a user turn, resume the main agent, rename the chat, or send the suggested text automatically.
Explain the additional model usage in the feature control.

Cache by session and completed turn so rerenders and pane selection do not repeat inference.
Discard late results after another turn, session replacement, a new draft, or feature disablement.
Preserve existing attachments, quotes, slash completion, message queues, and steering behavior.
Keep errors and unavailable providers from blocking normal typing.

The integration needs component, transport, and browser proof for full-width chat and each split pane.
A native runner change also needs a qualified host update. The earlier release changed only the UI, so it does not establish this compatibility.
The current deployed backend, host processes, and UI remain unchanged.

## Current harness and OMP

Live session metadata reports `codex-native` for this chat on Eagle WSL.
Its path is Omnigent web, native Codex, then OpenAI.
OMP is not between Omnigent and this session's model.

Read-only ACP configuration inspection found Cline on Eagle WSL, and Cline, Cline (thinking), and Oh My Pi on native Windows Eagle.
No provider secrets or configuration values were copied into this record.
OMP coordination was deferred when Alex said that OMP could come later.

The intended OMP workflow remains a separate coordinator chat that creates Claude Code, Codex, and Cline child chats through Omnigent tools.
Each child keeps its own native or ACP harness. OMP does not replace those harnesses.
The [OMP guide](primary-platform-omp.md) records that design and the remaining placement and live-coordination proof.
