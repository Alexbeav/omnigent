# OMP as an Omnigent session coordinator

## Eagle WSL pilot installed, 2026-10-16

OMP `18.11.1` is installed in an isolated Eagle WSL directory:
`/home/alexbeav/.local/share/omnigent-omp/18.11.1/omp`.
The official GitHub `omp-linux-x64` asset matches its release digest and checksum manifest.
Its SHA-256 is `bf1e86a935b1ea26166a5280001eccea1205e6c21efe1b5853f0fd368c754974`.
No Bun installation or shared-host restart was required.
The existing Windows OMP and patched Hermes installations are unchanged.

The isolated profile is `~/.omp/profiles/omnigent-coordinator/agent`.
It selects `openai-codex/gpt-6.1-sol` and denies direct shell, edit, browser and OMP task tools.
This profile is not an operating-system sandbox.
Eagle WSL's ACP list contains a separate `OMP Pilot` entry, with Omnigent tools enabled and `permission_mode: auto`.
The existing Cline entry and unrelated configuration are preserved.
The host advertised `acp:omp-pilot: true` through normal dynamic discovery.
No sign-in task, WSL setting or service owner changed.

The ACP handshake and session creation pass against the installed binary.
It advertises image input and load/resume/fork/list support.
The qualified Omnigent MCP helper lists the selected tool schemas and completes a transport call against a fixture callback.
That fixture does not establish live Omnigent dispatch or worker coordination.
The isolated model probe fails because no allowed model has usable credentials.
No authenticated inference or two-turn persistence is proven.

OMP's native-Codex credential import dry run skipped the auth file because its format is unsupported.
No credential was imported, copied, rewritten or refreshed.
`omp auth import` accepts OMP exports, while `auth-broker import` accepts CLIProxyAPI records.
The existing Cline login is not a documented OMP credential-import format.
The profile has zero stored credential rows and no provider API key in the inherited environment.
Alex must complete the supported OMP login in a local terminal:

```bash
/home/alexbeav/.local/share/omnigent-omp/18.11.1/omp --profile omnigent-coordinator login openai-codex
```

Use the intended existing account in the provider's own sign-in flow.
This creates an OMP profile login and does not replace the native Codex home.
The parent can create an idle pilot from this agent config; wait for login before inference:

```text
/home/alexbeav/.local/state/omnigent-investigations/remaining-enhancements/scope-1/implementation/omp-pilot/config.yaml
```

The parent's first idle creation attempt returned HTTP 400 because `os_env.cwd` was absolute.
Schema parsing alone did not exercise the server's uploaded-spec working-directory check.
The corrected value is `.local/state/omnigent-investigations/remaining-enhancements/scope-1/implementation/workspace`, relative to the parent workspace `/home/alexbeav`.
It resolves to the same isolated directory, and the qualified server's uploaded-spec check accepts it.
Actual corrected Omnigent creation awaits the parent's retry; this correction created no chats or model requests.
The evidence is `implementation/cwd-creation-validation.json`.

The pilot owner did not create an Omnigent child chat.
The parent must prove two coordinator turns, then create distinct native Claude, native Codex and ACP Cline workers.
Reopen each worker and send a follow-up to the same session ID.
Make sure that actual harnesses, host bindings, completion delivery and attachments match the intended task.
The question-control and suggestion features remain separate application workstreams.

Rollback removes only the `OMP Pilot` ACP list entry.
Preserve the isolated profile, credentials, binary and transcripts for diagnosis.
Do not restore an entire old global configuration file over later edits.
The private setup, qualification and rollback record is under
`~/.local/state/omnigent-investigations/remaining-enhancements/scope-1/implementation/`.
Current operational state belongs in the homelab `Common/Infrastructure-State.md` note.

## Decision

Use Oh My Pi (OMP) as the coordinator chat. OMP creates three separate
Omnigent child sessions for Claude Code, Codex, and Cline. Each child keeps its
own transcript, harness, tools, model selection, and session identity.

Do not use OMP native subagents for this workflow. An OMP native subagent stays
inside the OMP process and does not become an Omnigent child session.

Do not treat Claude, Codex, and Cline as model APIs inside OMP. They are CLI
harnesses that Omnigent starts in separate sessions.

## Confirmed setup

The runtime `sys_agent_list` result on 2026-10-15 contained this selectable
agent:

- Agent ID: `36019311800f1f81f7da81659d6bba79`
- Name: `oh-my-pi`
- Harness: `acp:oh-my-pi`
- `available_on_host`: `true`

The same result contained launchable native Claude Code and Codex agents, and
an ACP Cline agent. This document does not pin their agent IDs. The coordinator
must resolve current IDs with `sys_agent_list` before it creates children.

Read-only configuration inspection located `Oh My Pi` in
`C:\Users\Alexbeav\.omnigent\config.yaml` on Windows Eagle.
On 2026-10-15, the WSL configuration at `~/.omnigent/config.yaml` contained Cline only.
The report contains no authentication values.

A disposable OMP child launch from this WSL session failed before an OMP turn:

```text
ACP agent 'oh-my-pi' is not configured on this runner. Check the selected host's ACP configuration.
```

The agent catalog had reported `available_on_host: true` because readiness
collapsed `acp:oh-my-pi` into the generic `acp` family.
Having Cline configured therefore incorrectly marked OMP as available too.
This patch preserves ACP agent identity in readiness and publishes configured agent slugs.
Older hosts with only a generic ACP report return unknown for a specific agent.
The fix does not install OMP or change either host's configuration.

Choose a coordinator host with OMP and the required worker harnesses configured.
Children created with `sys_session_create` inherit the parent's runner.
The current tool does not select another host for each new child.
Cross-host peer messages can contact existing sessions, but they do not create workers there.

## Confirmed capability path

Omnigent builds every selectable ACP agent from one generated bundle. The
bundle sets both `spawn: true` and `peer_messaging: true` in
`omnigent/server/app.py`.

The repository tests prove that the generated YAML retains both values after
parsing:

- `tests/test_acp_agent_bundle.py::test_acp_bundle_grants_spawn`
- `tests/test_acp_agent_bundle.py::test_acp_bundle_spawn_survives_parse`
- `tests/test_acp_agent_bundle.py::test_acp_bundle_grants_peer_messaging`

`spawn: true` exposes these tools through the Omnigent MCP relay:

- `sys_agent_list`
- `sys_session_create`
- `sys_session_send`
- `sys_session_close`
- `sys_session_list`
- `sys_session_get_info`
- `sys_session_get_history`
- `sys_list_models`
- `sys_read_inbox`
- `sys_cancel_task`

`omnigent/tools/manager.py` defines this tool gate. The ACP executor passes the
same tool schemas in `session/new.mcpServers` when `omnigent_mcp` is enabled.
See `omnigent/inner/acp_executor.py::_session_mcp_servers`.

The picker agent already uses the ACP bundle path and needs no duplicate coordinator agent.
The code change in this work corrects its host availability report.

## Orchestration flow

Use this sequence for each coordinated request:

1. Call `sys_agent_list` once.
2. Select one available agent for each required harness: `claude-native`,
   `codex-native`, and `acp:cline`.
3. Reject a row when `available_on_host` is `false`. Treat `null` as unknown.
4. Call `sys_session_create` once per selected agent. Pass its `agent_id`, a
   task title, and no initial message.
5. Save each returned `conversation_id`.
6. Call `sys_session_send` with each child `conversation_id` and its task.
   Multiple sends in one OMP response run concurrently.
7. End the OMP turn. Omnigent sends a completion notice when a child finishes.
8. Call `sys_read_inbox` once to collect finished child results.
9. Use `sys_session_get_history` only when a result is missing or unclear.
10. Send follow-up work to the same `conversation_id` to keep that child's
    transcript and harness identity.
11. Use `sys_cancel_task` with the returned task ID to stop tracked work.
12. Use `sys_session_close` only when Alex asks to close a child session.

Creating an idle child before the first send makes the tracked-work boundary
clear. `sys_session_create` returns a session handle. The later
`sys_session_send` returns a task handle, and its result enters the OMP inbox.

## Peer messaging

The generated ACP bundle also grants `peer_messaging: true`. This grant lets
OMP send to a same-owner session outside its own child tree.

The default coordinator path does not need peer messaging. OMP owns the three
children that it creates, so child-mode `sys_session_send` provides tracked
results through `sys_read_inbox`.

A peer send is different. It is an untracked message, it returns no inbox
result, and the receiving session sees an envelope that names the sender.
Use it only to contact an existing session that OMP did not create. The runner
checks same-owner access and applies a send limit. See
`omnigent/runner/tool_dispatch.py::_send_to_peer_session`.

## Ownership boundaries

Omnigent owns the parent-child session tree and each child transcript. OMP sees
the child through MCP tool results and the Omnigent inbox.

Each child owns its CLI harness process and model authentication. OMP does not
receive or copy Claude, Codex, or Cline credentials. `sys_session_create`
passes a registered `agent_id`, not an authentication value.

Model selection is per child. Omit `model` and `reasoning_effort` to use that
agent's default. If OMP needs an override, it must use a value accepted by the
selected child harness.

Image and file continuity is not implicit across sessions. A text reference to
an attachment does not transfer its bytes. The current `session_id` send path
does not accept `file_ids`, so OMP must ask a child to read a shared workspace
path or use another explicit transfer path.

Cancellation uses a task ID, while closing a child is a separate operation.
Stopping the parent runner can interrupt its child processes and tasks.
Test process shutdown separately from child transcript closure.

## Acceptance tests

### Static capability tests

Run these commands from the repository root:

```bash
uv run --no-sync python -m pytest -q \
  tests/test_acp_agent_bundle.py \
  tests/tools/test_peer_messaging_tools.py \
  tests/tools/test_manager.py::test_spawn_flag_registers_write_tools_without_sub_agents \
  tests/tools/test_manager.py::test_session_send_schema_drops_named_mode_without_sub_agents
git diff --check
```

Expected result: all selected tests pass, and `git diff --check` prints no
errors.

### Isolated coordinator test

Use an isolated Omnigent server and disposable repository. Do not run this test
against a live worktree.

1. Start a chat with agent `36019311800f1f81f7da81659d6bba79`.
2. Ask OMP to call `sys_agent_list` and report only names, harnesses, and host
   availability.
3. Ask OMP to create one child for each required harness without a message.
4. Ask each child to return a different fixed token through
   `sys_session_send`.
5. Open the session tree while the tasks run.
6. Wait for completion notices, then ask OMP to call `sys_read_inbox` once.
7. Send a follow-up to each saved child session.
8. Cancel one slow child task by its task ID.
9. Close the OMP chat only after the child states are recorded.

The test passes when three distinct child sessions appear under OMP, each uses
the requested harness, and each follow-up reaches the same child transcript.
The inbox must return each tracked result once. Cancellation must stop only the
selected task. Closing the parent must not silently call
`sys_session_close` for every child.

### Peer-message test

Create a same-owner session outside the OMP child tree. Ask OMP to send one
message to its session ID.

The test passes when the target receives a marked peer envelope and no tracked
result appears in the OMP inbox. A different-owner target must fail.

### Attachment test

Attach one image to the OMP parent. Ask OMP to delegate an image-content
question to one existing child by `session_id`.

The test passes only if the child receives the image bytes through an explicit
supported path. A successful text-only send with no image content is a failure.
This test is expected to expose the current file-transfer gap.

## Verification and remaining gaps

The ACP capability tests passed 16 checks in the integration worktree.
The readiness tests passed 116 checks across host discovery, configuration, and session creation.
These tests use isolated fixtures and establish capability wiring and selection behavior.
The live OMP child failed during runner configuration lookup and never reached a model.

The remaining end-to-end proof needs a coordinator on the chosen host, then one worker for each requested harness.
File transfer to existing children, interruption, and parent-runner shutdown remain separate acceptance checks.
No OMP installation, authentication, live configuration edit, or service restart took place in this workstream.

## Primary sources

- OMP README: https://github.com/can1357/oh-my-pi/blob/main/README.md
- OMP ACP implementation: https://github.com/can1357/oh-my-pi/blob/main/packages/coding-agent/src/modes/acp/acp-agent.ts
- OMP task agents: https://github.com/can1357/oh-my-pi/blob/main/docs/tools/task.md
- Omnigent repository: https://github.com/omnigent-ai/omnigent
- Generated ACP picker bundle: `omnigent/server/app.py::_build_acp_bundle`
- MCP relay setup: `omnigent/inner/acp_executor.py::_session_mcp_servers`
- Tool registration: `omnigent/tools/manager.py::_register_sub_agent_tools`
- Session creation: `omnigent/tools/builtins/spawn.py::SysSessionCreateTool`
- Child and peer dispatch: `omnigent/runner/tool_dispatch.py`
