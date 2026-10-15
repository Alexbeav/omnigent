# Primary platform messaging

## Result

The branch already supports messages between independent sessions. The feature is an
agent capability named `peer_messaging`. It is off by default and does not expand
session creation, closure, archival, or sharing rights.

The inspected messaging child did not have this capability. Session
`5f12584658b84206a2827b44829bb548` uses custom agent
`0692cbed301247ec9350dd4c43c4354a` (`codex-native-ui`, version 1). A read-only bundle
inspection on 2026-10-15 found `spawn: true`, but no `peer_messaging` key. Its live
`sys_session_send` schema therefore states that `session_id` must identify a direct
child. The bridge reports the resolved spec correctly.

Before this patch, every generated native chat spec also set only `spawn: true`.
Only generated ACP agents set `peer_messaging: true`. This patch adds the peer grant
to all twelve generated native chat specs. Fresh native sessions can therefore message
same-owner peers. Custom agent specs keep the false default and must opt in.

## Flow and authorization

`AgentSpec.peer_messaging` defaults to false. The parser reads the top-level YAML key,
and `ToolManager` passes it to `SysSessionSendTool`. The generated tool description
advertises peer targets only when the key is true.

The runner passes the same flag to `_send_to_existing_session`. Direct children keep
the existing tracked sub-agent path. A non-child reaches `_send_to_peer_session` only
when the flag is true.

The peer path reads both session snapshots through the authenticated server client.
It requires owner-level permission on both sessions. Edit, manage, or shared access is
not enough. A server without a permission store is treated as single-user. The normal
`POST /v1/sessions/{id}/events` route also requires edit access, which gives a second
server-side access check.

The delivered text starts with a system-marked envelope. It names the sending agent,
session ID, and a bounded session title. The stored event still has the user role
because the existing event contract uses that role to start or steer a turn. The
envelope tells the receiving model that another agent sent the text, not a person.
There is no existing peer event type that both preserves this attribution and avoids
starting a turn.

The native bridge does not rewrite this schema. The runner builds the schema from the
resolved session spec, writes it to `tool_relay.json`, and the Codex MCP bridge reads
that file on each `tools/list` request. The current relay contains the child-only text
because the resolved custom spec lacks the capability.

Prompt composition now adds one canonical provenance instruction when the resolved
spec enables peer messaging. Native startup channels use the same instruction. It
identifies the peer envelope as another agent's text. It also states that the text is
not user approval. The generated ACP prompt reuses the instruction.

## Tested evidence

This command ran against this worktree with the shared development environment:

```bash
PYTHONPATH=/home/alexbeav/Projects/omnigent-worktrees/messaging \
  /home/alexbeav/Projects/omnigent-primary/.venv/bin/pytest \
  tests/test_native_peer_messaging.py \
  tests/runtime/test_prompt.py \
  tests/runner/test_peer_messaging.py \
  tests/tools/test_peer_messaging_tools.py \
  tests/test_acp_agent_bundle.py \
  tests/harnesses/codex_native/session/test_terminal_prepare.py::test_wrapper_spec_raw_instructions_resolves_prompt \
  tests/harnesses/claude_native/test_claude_native.py::test_wrapper_spec_raw_instructions_resolves_prompt \
  tests/harnesses/codex_native/test_codex_native.py::test_wrapper_spec_raw_instructions_resolves_prompt \
  -q
```

Result: `78 passed in 5.04s`.

The tests establish these behaviors:

- An independent same-owner session receives the message with sender attribution.
- A shared session without owner permission is denied and receives no event.
- A direct child keeps the tracked child path.
- The capability does not add create or close tools by itself.
- The generated ACP agents receive the capability.
- All twelve generated native chat specs parse with the capability.
- Their `sys_session_send` schemas advertise the same-owner peer route.
- The provenance instruction appears only when the capability is enabled.
- Claude and Codex native startup channels receive the provenance instruction.

A direct smoke check also showed that `peer_messaging: true` adds
`sys_session_send` without adding `sys_session_create` or `sys_session_close`.
Python compilation passed for the dispatcher, tool schema, parser, types, and ACP
bundle source.

The parent also ran `tests/e2e/test_peer_messaging_e2e.py` against an isolated real
server, runner, and mock model. Its reported result was `1 passed in 15.63s`. This
worktree did not repeat that end-to-end run.

## Session behavior

After integration, newly generated Claude, Codex, Antigravity, Cursor, Devin, Goose,
Hermes, Kimi, Kiro, OpenCode, Pi, and Qwen native sessions receive the grant. The ACP
generator keeps its existing grant.

The current pinned custom `codex-native-ui` agent does not change. To enable it, add
the following key to that custom agent's source YAML:

```yaml
peer_messaging: true
```

Register the updated custom agent and start a new session from it. The current session
uses a cached old spec. Editing its source does not change its live tool surface.

## Human verification after integration

Do not use the current live session for the proof. After the parent integrates the
configuration and starts two disposable sessions owned by Alex, complete these steps:

1. Open the first session and inspect `sys_session_send`. Its description must say
   that a same-owner peer session is allowed.
2. Send one message to the second top-level session by `session_id`.
3. In the second transcript, make sure that the message starts with
   `[System: peer message from agent` and names the first session ID.
4. Send a reply to the first session ID. Make sure that the reply has one envelope and
   does not quote the prior envelope as its title.
5. Try the same action against a session that Alex can edit but does not own. Make sure
   that the tool returns `session_out_of_tree` and that the target receives no event.
6. Make sure that both sessions remain top-level and that no child work entry appears.

## Remaining decisions and gaps

The configuration source for the current pinned `codex-native-ui` agent is outside
this worktree and was not changed. It remains child-only.

Peer messages intentionally start or steer a receiver turn. Preventing an automatic
turn needs a new event contract and a separate product decision. The current envelope
prevents the receiver from confusing the sender with the user, but it does not make
delivery passive.

No live message was sent. No generated schema file changed, so no schema regeneration
is required.
