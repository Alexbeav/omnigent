# Suggested replies in chat composers

Status: a composer prototype is implemented on `feature/composer-prompt-suggestions`.
It is not connected to a suggestion source and is not deployed.
The source of suggestions is still under review: reuse an available provider interface, or generate a fallback with a separate background model request.
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

### Codex

Codex launched Composer Predictions on 2026-10-09.
The desktop beta supports adults on personal ChatGPT Pro plans in local and SSH threads with GPT-6 Astra or GPT-6.1 Sol.
Tab accepts an editable draft; acceptance does not send it.
During the beta, generating these native predictions costs nothing extra and does not consume Codex limits or credits.
That desktop entitlement does not establish access from a third-party integration.

The installed Codex CLI is 0.162.1.
Its generated experimental app-server schema declares `thread/prediction/request` and `thread/prediction/updated`.
The earlier investigation incorrectly reported that these declarations were absent: its search terms missed `prediction`.
However, declaring the interface does not establish that its handler works.
An isolated runtime probe successfully initialized the installed app-server with experimental APIs enabled, then requested a prediction for nonexistent thread and turn IDs.
It returned JSON-RPC error `-32601`: `thread/prediction/request is not implemented yet`.
The public server source at `6ae8b8aa7c608730d4315d59c5c081897ae02780` contains the same explicit rejection.
The probe used an empty temporary home, no copied credentials, and no real thread; it did not request model inference and its process was removed.
Omnigent cannot obtain native predictions merely by calling that method on this installed version.

### Oh My Pi

OMP added built-in composer predictions in version 18.9.0 on 2026-10-11.
The `composer.predictions` setting defaults to false.
When enabled in the interactive terminal interface, a completed turn can trigger a separate model request using the conversation context.
Tab or Right Arrow accepts the resulting ghost text as a draft.
This extra request consumes model usage, which OMP includes in session totals and `/stats`.

The source at `a536558dc21634462c1b2647676953204569779c` connects its prediction controller to the interactive editor.
Its ACP agent does not forward composer predictions, and the RPC word-prediction service is a different feature.
Therefore, the current Omnigent `omp acp` connection needs an adapter before it can deliver those next-message suggestions to the web composer.
Read-only inspection found OMP 18.2.8 installed on native Windows Eagle, which predates the built-in feature.
No upgrade or settings change was performed.

### Hermes

The official Hermes catalog lists `next-prompt` 0.3.0 as a community Desktop plugin, requiring Hermes 0.21 or later.
It is not presented as a built-in CLI prediction setting.
The plugin generates a suggested reply after a turn and shows a pill below the Desktop composer.
Clicking the pill or pressing Ctrl/Command+Shift+Y inserts an editable draft without sending it.
It makes an additional model request; its auxiliary model can be configured separately.
The plugin exposes a suggestion through its own REST endpoint and uses the Desktop composer API to insert text.
Using that plugin in Omnigent would require a connection to its running backend and a web composer adapter; installing it alone does not add this UI to Omnigent.

### Implication for Omnigent

Omnigent already has isolated background inference for session titles through the selected harness.
That is a useful starting point for a generated fallback, with a distinct next-prompt task and response contract.
Do not silently ask the title endpoint for a title and present that output as a suggested reply.

Provider suggestions belong to their original session and completed turn.
Prefer a working provider interface where the active harness exposes one.
The installed Codex prediction handler is unavailable, and the current Claude interactive and OMP ACP paths do not automatically forward their suggestions.
A custom fallback remains possible, but its additional model usage is separate from the free Codex desktop beta.

Primary references:

- [Claude Code prompt suggestions](https://code.claude.com/docs/en/interactive-mode#prompt-suggestions).
- [Codex app-server protocol](https://learn.chatgpt.com/docs/app-server).
- [Codex release date](https://learn.chatgpt.com/docs/changelog#composer-predictions-in-codex).
- [Codex prediction behavior, eligibility, and beta usage](https://help.openai.com/en/articles/20001601-composer-predictions-in-codex).
- [Codex prediction handler](https://github.com/openai/codex/blob/6ae8b8aa7c608730d4315d59c5c081897ae02780/codex-rs/app-server/src/message_processor.rs#L1457).
- [OMP 18.9.0 release notes](https://github.com/can1357/oh-my-pi/blob/a536558dc21634462c1b2647676953204569779c/packages/coding-agent/CHANGELOG.md#L307).
- [OMP setting and usage description](https://github.com/can1357/oh-my-pi/blob/a536558dc21634462c1b2647676953204569779c/packages/coding-agent/src/modes/settings.ts#L1000).
- [OMP interactive prediction controller](https://github.com/can1357/oh-my-pi/blob/a536558dc21634462c1b2647676953204569779c/packages/coding-agent/src/modes/controllers/composer-prediction-controller.ts).
- [Hermes next-prompt catalog entry](https://hermes-agent.nousresearch.com/docs/plugins/next-prompt).

Pinned upstream sources and the isolated Codex RPC result are recorded privately under `.omnigent/verify/prompt-suggestions-20261016/recheck/`.
This recheck supersedes the earlier schema-availability conclusion in `research.json`.

## Remaining integration work

After selecting an available suggestion source, bind suggestions to completed assistant turns and the original session ID.
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
