# Omnigent primary platform work

This record covers Alex's five requests from 2026-10-15 and the later child-chat visibility report.
The starting revision is `e88754218` on `feature/session-orchestration-v0.17`.
The integrated work is on the local branch `feat/primary-platform` in `~/Projects/omnigent-primary`.
The live editable checkout remains `~/Projects/omnigent`.

The current v0.18.0 deployment and contribution work are covered by the [upstream update record](primary-platform-upstream-update.md).

## Result by request

| Request | Implemented or established | Limit |
| --- | --- | --- |
| Independent chat messaging | Generated native agents receive the existing same-owner peer grant. Native startup instructions identify messages from other agents. | Existing sessions retain pinned definitions. Deploy the changes and start or update agent definitions before live use. |
| Web pictures | Shared validation accepts supported image filenames when browser MIME data is empty or generic. Sending uses an image content block. | The exact cause of the original interface report remains unconfirmed. Live vendor image turns were not tested. |
| Three tall chats | Three desktop columns, per-pane model and effort controls, sidebar edge-drop, header drag popouts, resizing, separate drafts and sends, popout, and close/reopen. | Widths are not saved after reload. Actual OS desktop drops and popup placement depend on the browser. |
| Background hosts | Browser connection instructions include `--background`; the guide includes WSL lifetime and the working PowerShell launch form. | Automatic startup after Windows login or reboot is not installed by this patch. |
| OMP coordinating workers | Existing ACP relay already exposes child creation, sending, inbox, and cancellation. Fixed false availability when another ACP agent is configured. | OMP is configured on Windows Eagle, not this WSL runner. Coordinator placement and a three-worker live proof remain. |
| Child visibility | The selected root's sidebar shows child titles, statuses, and navigation links. | The Agents panel remains the full tree view. |

Details: [messaging](primary-platform-messaging.md), [images](primary-platform-attachments.md),
[panes](primary-platform-panes.md), [background hosts](background-hosts.md), and [OMP](primary-platform-omp.md).

## Work allocation

Four Omnigent child chats investigated messaging, images, panes, and OMP in separate Git worktrees.
The parent integrated the patches, added sidebar child links, reviewed failures and permissions, and ran combined checks.
The worktrees under `../omnigent-worktrees/` retain their scoped work.

## Combined evidence

The verification environment uses private state and mock model endpoints.
It does not use the running host's database or vendor credentials.

| Check | Observed result |
| --- | --- |
| Web components for attachments, session state, connection dialogs, and panes | 1222 checks passed before the final header review. |
| Final AppShell, pane container, and SideChatPane checks | 178 checks passed. |
| Native grants, prompt composition, peer ownership, generated bundles, and isolated peer exchange | 134 checks passed; the later lifecycle parsing check passed in its focused suite. |
| Peer lifecycle and shared native startup seam | 29 checks passed. |
| Host readiness and creation preflight | 116 checks passed. |
| ACP orchestration capability gates | 16 checks passed. |
| Browser attachment flows, including picker, paste, drop, and image-only sends | 16 checks passed. |
| Browser multi-chat journey | Passed: add, edge-drop, distinct drafts, correct send destination, resizing, popout, close/reopen, mobile collapse, and child visibility. |
| Native image adapters and isolated image-to-model transport | Three checks passed. |
| Existing detached-host and user-service CLI checks | 17 checks passed before the outage. |
| Feature map contract | 131 checks passed after the final documentation changes. |

The pre-commit checks passed, including Python and TypeScript type checks.
The final verification manifest is `.omnigent/verify/primary-platform-verification.json`.
Browser evidence is under `.omnigent/verify/pane-evidence/` and `.omnigent/verify/resume/image-evidence/`.
These are local evidence, not product assets to commit.

## Live observations

Alex enabled both WSL idle settings and restarted the host through the PowerShell command.
The settings were read back, and this same conversation resumed through the detached process.
This establishes configuration presence and resumed access, not Windows reboot recovery.
The homelab state and operational notes record the distinction.

A disposable OMP child failed before a model turn because this WSL runner lacks the `oh-my-pi` ACP entry.
Safe configuration inspection found the entry in Windows Eagle's configuration.
No credential value was read or copied into this record.
A catalog membership or a generic ACP-ready flag does not establish that a particular ACP agent can launch.

## OMP architecture and next decision

Alex selected OMP as the coordinator for separate Claude Code, Codex, and Cline chats.
Use OMP's Omnigent MCP tools to create and drive those children.
OMP's internal subagents and provider models are separate mechanisms.

The smallest placement puts OMP and its three worker harnesses on the same host.
The current child-creation tool inherits the parent's runner and has no per-child host selector.
Keeping the coordinator on Windows while launching workers on WSL needs a separate placement design.
Same-owner peer messages can contact existing sessions across hosts, but they are not tracked child tasks.

After placement is chosen, create a disposable coordinator and ask each worker for a distinct token.
Make sure that three distinct transcripts appear, replies arrive through the OMP inbox, and follow-ups keep each worker's identity.
Then test cancellation, process restart, and explicit screenshot transfer separately.

## Trying the code

The updated UI is live at [the NAS server](http://172.16.1.8:8090).
Reload the browser with **Ctrl+Shift+R** to load the new bundle.
On a desktop, open a chat and use **Add pane…** in the header twice to select two more chats.
Use **Add > Files and images** in a composer to attach a picture.

Use an isolated environment from [Verify Omnigent](../feature-map/skills/verify-omnigent/SKILL.md).
Build this checkout, start its environment, and open the URL it reports.
The linked feature notes contain focused test commands and manual checks.

For panes, open a chat and add a second through `Add pane…`.
Drag a third sidebar row onto the marked chat edge.
Type a distinct draft in each, send one, resize a divider, then close and reopen a pane.
Use a pane's window button to request a separate window.
A shared read-only chat must show no send composer.

For pictures, use **Add > Files and images**, paste an image, and drop a file.
Send one image without text and inspect the stored user bubble.
For independent messaging, use fresh generated native agents and a disposable same-owner peer.
Existing pinned custom definitions need an explicit `peer_messaging: true` update.

## Follow-up: pane controls and dragging

Alex requested the primary chat's model and reasoning controls in every ordinary pane.
The provider stays fixed. Each pane reads its own model catalog, reported model and effort.
The shared picker and explicit conversation targets prevent changes from reaching a neighboring chat.
Host, permission and Codex Plan controls also belong to the pane.

Use a header popout button or release a dragged header or sidebar row beyond the page to request a separate window.
Headers handle Escape, pointer cancellation and lost capture.
An outside-viewport release is supported when the browser delivers it.
The recorded Chromium release uses browser automation and does not establish real OS desktop-drop behavior.

Ordinary panes also share queueing, steering, keyboard shortcuts and the Always steer preference.
Queue flushes honor each conversation's live status, including a busy pane with a stale idle sidebar row.
The add control now lives in the primary header. Sidebar drops place or move a chat on either side of any pane.
The `paneOrder` query preserves visual order without changing the primary route.
The left and right halves now show the split preview; the separate window drop target is removed.

The Claude bridge patch excludes diagnostic `api-request-blob` snapshots from transcript forwarding.
These snapshots duplicated real user records and could expose native reminders.
Display and copy extraction also hide complete or truncated reminder blocks.
Stored rows and existing native history stay unchanged.
New regressions cover both transcript readers and consecutive executor/bridge calls at the mocked terminal-paste boundary.
This is not a real-provider end-to-end test. Existing Claude runners need a targeted reconnect to import the host-side parser fix.

Follow-up verification completed on 2026-10-16 (local time).
The three isolated Chromium journeys passed in 10.84 seconds against the final production build.
They cover six pane-specific model/effort/permission updates and reload, scoped queue edit/remove/send-now/idle flush/bulk steer, left/right placement, resize, popout and cancellation.
The queue journey keeps the sidebar idle while the Claude pane's live stream is busy.
The primary draft remains unchanged and all mocked backend routes are accounted for.
Store checks passed 585 tests; composer checks passed 361 tests; the other pane/shell/bubble component checks passed 192 tests.
Python parser and feature-map checks passed 136 tests.
Local evidence is under `.omnigent/verify/`, including `final-pane-browser.xml` and `pane-final-*.log`.
The first deployment record below is historical; the follow-up deployment is recorded at the end of this note.

## First rollout, 2026-10-15

The NAS server was updated on 2026-10-15 at Alex's request; OMP coordination was deferred.
The live host checkout and host processes were not updated or restarted.
New built-in native agent definitions were refreshed at server startup; existing sessions keep their pinned definitions.
The runtime startup-instruction changes on hosts still need a later host update.

| Deployment evidence | Result |
| --- | --- |
| Application source | `9b8bdd0dd8d73ab5cfe1e4ba3c9b61bb4098a3e6`, branch `feat/primary-platform`; server version remains `0.17.0`. |
| Compose image | `registry.crosstalkis.com/omnigent-server:sha-9b8bdd0dd@sha256:4b66b4ab7d930b293f36caf46cede22c3a859a935369ed589193daef24f21e21` |
| Image construction | Existing digest-pinned runtime plus committed application source and the verified web bundle; dependency manifests and SDKs are unchanged. The full Dockerfile build was stopped during slow dependency downloads. |
| Isolated image rehearsal | Backup restored into a private Postgres container; new image startup and internal health passed, with 92 conversations and 59,904 items unchanged. |
| Live cutover | 93 conversations and 60,013 items before and after; every original row identifier retained; schema unchanged at `mm1a2b3c4d5e`. Other chats added data between the earlier backup and cutover. |
| NAS configuration | Compose pin committed locally in `homelab-ulduar` as `a21f0aa`; not pushed. Unrelated monitoring changes preserved. |
| Served UI | All 70 entry JavaScript and CSS assets match the verified bundle by SHA-256; entry script is `index-Deb4mQkC.js`. |
| Service checks | New server healthy, zero restarts, accounts auth preserved. Only the Omnigent server container changed; Postgres and all unrelated containers retained their identities and restart counts. Transit Vault remained healthy and unsealed. |
| Cutover backup | `/volume1/docker/stacks/omnigent/backups/primary-platform-20261015-9b8bdd0dd/cutover.dump`, 54,749,058 bytes, SHA-256 `b74a0726dcd2c003f15ec75195a3de3981e5137782c08089e759cc2eee1dc9dd`. |

The previous Compose file, image, rollout script and deployment JSON remain in that backup directory.
Build recipes, logs, bundle hashes and container comparisons are under `.omnigent/verify/deployment/` locally.
Rehearsal containers and their private network were removed; temporary NAS registry credentials were removed after the pull.
Two rehearsal setup checks needed correction: Postgres readiness must use TCP to avoid its temporary initialization socket, and the internal Docker network required checking health inside the container.

To roll back this server-only change, restore the saved Compose file and run
`sudo /usr/local/bin/docker compose -f /volume1/docker/stacks/omnigent/docker-compose.yml up -d --no-deps omnigent`,
then check `/health`. No database restore is needed for this patch, which has no migration.
Validate fresh native agents with disposable chats before updating long-running sessions or hosts.

## Follow-up rollout, 2026-10-16

The live server runs application `2050948e3ed0bd9a93fe81974fe3ed0a56b8d2ec` on `feat/primary-platform`,
with image `registry.crosstalkis.com/omnigent-server:sha-2050948e3@sha256:821c003af23d7acbdde711061b29a8b539f4c533fc76625ee6e3be3dd667924a`.
Version remains `0.17.0`, with unchanged dependencies and database schema.
The container smoke check passed the actual diagnostic-request exclusion and confirmed the source identity and bundled UI.
The digest was pushed and pulled before cutover; temporary NAS registry credentials were removed.
The Windows Docker CLI required a GNU tar build context; the initial PAX archive was rejected before any image build.

The quiescent database dump contains 95 conversations and 60,926 items.
Every original row ID survived; post-cutover counts are identical and schema remains `mm1a2b3c4d5e`.
Backup: `/volume1/docker/stacks/omnigent/backups/pane-followup-20261016-2050948e3/cutover.dump`, 56,316,001 bytes, SHA-256 `e9844fa6fc17b257ee9d86e9aac8e7373a7a7cc3c9af2cf412829de7e6d83212`.
The previous Compose and image remain with the rollout script and deployment JSON in that directory.

All 448 served JavaScript and CSS files match the verified production build; entry script `index-CHxJcFjo.js`.
Accounts auth and server health pass; the server has zero restarts.
Only `omnigent` changed. PostgreSQL and 28 unrelated containers kept their identities, start times and restart counts.
Transit Vault remains initialized, healthy and unsealed.
The Compose pin is local `homelab-ulduar` commit `f3e76cb92`; it is not pushed, and unrelated monitoring changes remain untouched.
Artifacts are under `.omnigent/verify/pane-rollout/`.

Host installations were not replaced. The live editable checkout already contains the Claude parser patch.
The idle Claude session `189d5d7ce28b4b1ea7ac7d0938efafdf` was reconnected through
`retry_session` (HTTP 202, `recovered=true`, `runner_relaunched`): runner `19983`
exited and fresh runner `5166` started from the patched editable installation.
The stale zygote rejected the changed graph; the host used direct-spawn fallback.
Shared host `1683` and zygote `1686` remained running; no user or assistant items
were added to that chat. Other existing coordinator runners can still create children
with their old imported parser until those coordinators reconnect. A disposable child
reused an old shared runner and reproduced duplication; it does not validate runner
`5166`. A clean two-turn live-provider test on the new runner remains unproven.
Existing polluted history remains unchanged.

Reload [the live UI](http://172.16.1.8:8090) with **Ctrl+Shift+R**.
Drag sidebar chats over the left/right halves, change a secondary pane's model and reasoning,
and queue a follow-up while that pane works. Its send-now arrow or the default Ctrl/Command+Enter shortcut steers only that pane.
The header popout button or an outside-page release requests a separate window. Browser policy controls OS desktop drops.

## Suggested replies, 2026-10-16

The [suggested next reply implementation](reply-suggestions.md) connects the
shared composer to an optional bounded background request for native Codex and
native Claude, in full chat and ordinary panes. It defaults off and uses additional model usage.
The complete server and web source `dc94d2137` is deployed at
[the live UI](https://omnigent.ulduar.crosstalkis.com).
The installed Codex prediction method remains unimplemented; native desktop beta
entitlement does not cover this extra request. Integration must retain the pending
async-question gate and the current-session provider/account resolution.
This chat still uses native Codex directly. The [isolated OMP pilot](primary-platform-omp.md)
is installed on Eagle WSL and awaits its separate OpenAI sign-in before worker qualification.

The [chat-link menu](primary-platform-panes.md) is available after reloading the UI.
Right-click a website or file link for **Open in Omnigent**, **Open in browser tab**,
and **Copy link**. Web clients use the current browser; the desktop shell can open
the default OS browser. Files preserve their source chat and cited position.

The new native question forwarder and prediction runner need the staged Eagle WSL
runtime. Its silent-start launcher now selects
`/home/alexbeav/Projects/omnigent-host-enhancements-dc94d2137/.venv-host`.
The running host was preserved during this coordinator turn.
Stopping it disconnects its managed chats, including this coordinator.
After all Eagle WSL chats are idle, run these commands in Windows PowerShell:

```powershell
wsl -d Ubuntu -u alexbeav -- /home/alexbeav/Projects/omnigent-host-enhancements-dc94d2137/.venv-host/bin/omnigent host stop --server http://172.16.1.8:8090
Start-ScheduledTask -TaskName OmnigentHostWSLV018
```

Then reopen or resume a native chat and request a fresh async question to test its
choices, custom answer and draft recovery. Previously stored plain questions do not
gain controls. Enable **Settings → General → Composer → Suggest my next reply**
to test an editable suggestion with Tab; acceptance never sends it.
Read the [usage limits](reply-suggestions.md) before enabling recurring generation.

The deployed image passed restored-database restart and rollback checks, 94 frozen
dependency checks and all 454 served asset hashes. The combined UI passed 1,822
web tests and 15 browser journeys. Isolated real-provider checks establish native
question/answer delivery, duplicate suppression and working prediction requests on
both providers. NAS Compose commit `840a0b2733180f651dc87b9e988b90009caedb8c` is pushed;
the unrelated monitoring edit is preserved. Current operational state and backup
metadata remain in the homelab state note and host-upgrade runbook.

## Question controls follow-up, 2026-10-16

The failed Codex test after moving this chat to Pegasus came from a host-version
mismatch. Pegasus still ran `38f30aa96`, whose forwarder drops native asynchronous
question metadata. The current fork already retains it, and server `dc94d2137`
already understands the structured message and ordinary reply contracts.

Native Claude Code uses its existing `AskUserQuestion` hook. New regressions
exercise selections, custom answers, denial and empty responses in all three
permission modes. Cline CLI 3.0.72 does not connect its native question callback
to ACP, so the framework now exposes `sys_ask_user` through the existing tool
relay. It returns an acknowledgement after question persistence; answers arrive
as ordinary user messages. Existing policy decisions are still enforced. No
server protocol change or permission-as-answer workaround is needed.

The shared asynchronous card is now labelled **Questions**, not **Codex question**.
Its ten browser-contract journeys cover Codex, Cline and native Claude in full
chat and split panes, including custom answers and source-chat routing after
focus changes. Native hooks, forwarding, server replies, tool registration,
policy handling, retained MCP operations and component tests also passed.
These isolated checks do not claim a fresh live-provider round trip on Pegasus.

The pinned Pegasus candidate is staged separately at
`/home/alexbeav/Projects/omnigent-host-question-controls/.venv-host`.
The systemd user service's question-controls drop-in selects that interpreter
for its next start and preserves the existing silent-start unit and PATH
drop-in. The old running service and active chats were not stopped.
After all Pegasus WSL chats are idle, activate it from a Pegasus WSL terminal:

```bash
env XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus systemctl --user restart omnigent-host.service
```

Resume a chat and ask for two structured questions. For Codex use the async
question tool, for Claude use `AskUserQuestion`, and for Cline use `sys_ask_user`.
Choose one suggested option and one custom answer, focus a different pane, then
Submit. Both answers must reach only the source chat and leave ordinary drafts
unchanged. Old plain-text questions do not gain controls.

The NAS server was not changed in this follow-up: Pegasus has no working SSH
route to it, and the remote deployment helper could not be tasked through this
session's child-only messaging scope. The generic heading awaits a later web
deployment; the existing server already supports the functional host changes.

### Pegasus activation confirmed, 2026-10-17

Alex restarted the Pegasus WSL host. Its active systemd service now runs PID
`187169` from the pinned question-controls environment at source `225e7f7af`.
This chat resumed, issued two native asynchronous questions, and received Alex's
selected answers, **Blue (Recommended)** and **Brief (Recommended)**, in one
structured reply. This confirms the live Codex question/answer round trip after
activation. Custom answers, pane routing, Claude and Cline retain the automated
coverage above; this check did not establish fresh human round trips for them.

### Cline tool connection verified, 2026-10-17

The first authenticated Cline test exposed a separate transport gap: CLI 3.0.72
retained ACP's per-session MCP list without loading it into the runtime. A
private settings-file probe also failed through the shared background runtime.
The same installed CLI successfully called a fixture MCP tool with a private
settings file and `CLINE_SESSION_BACKEND_MODE=local`.

Source `0d3c2686cdab243570caced15b07402dd6f92521` adds the generic
`{omnigent_mcp_config}` command marker. Its settings file uses the existing
session relay, is written before process spawn with mode `0600`, and is removed
on close. A disabled or unavailable relay prevents a command requiring the
marker from starting. Other launch commands remain literal argument vectors.
See the [ACP launch example](AGENT_YAML_SPEC.md#custom-acp-agents).

Pegasus's existing host checkout was fast-forwarded to that source. Its Cline
command now prefixes the existing Node/CLI command with
`/usr/bin/env CLINE_SESSION_BACKEND_MODE=local CLINE_MCP_SETTINGS_PATH={omnigent_mcp_config}`.
Existing provider/model flags, permission settings, login and shared Cline
profile were preserved. The runner detected the changed ACP command and
respawned only the idle Cline test harness; shared host PID `187169` stayed up.

The live [Cline test chat](https://omnigent.ulduar.crosstalkis.com/c/3761b068055a4b908a2da5623ad905d7)
then called `sys_agent_list` successfully and posted one `sys_ask_user` message
with two questions, both option lists and a deterministic reply ID. A read-only
API check and a live Chromium screenshot confirmed the card, choices and custom
answer control. Alex then requested a fresh question set, submitted **Green**
and **Just confirm receipt**, and Cline acknowledged both selections. The user
confirmed that questions work. This establishes the live human answer round
trip for Cline as well as the earlier Codex test and reported Claude test.
At this verification point, the NAS frontend still used the older **Codex
question** heading. The fleet/NAS rollout below subsequently deployed the generic
heading.

The focused ACP/runner/feature-map group passed **440 tests** with retries off;
the file-settings subprocess regression fails against the previous launcher.
Pre-commit passed. No frontend or server schema changed. Evidence is under
`~/.local/state/omnigent-investigations/native-question-controls-20261016/`,
including `cline-mcp-full-final.log`, `cline-live-question.json`, and
`cline-live-question-card.png`. The screenshot is local evidence, not a
committed product asset. Restore `config-before-cline-mcp.yaml` from that
directory and reconnect idle Cline chats to roll back the launch configuration.

### Remaining work after question acceptance, 2026-10-17

The question controls are accepted by Alex on Codex, Claude and Cline. The
remaining work is separate from that completed fix:

| Work | Current boundary |
| --- | --- |
| Deploy the pending web bundle | Complete: source `910495755` is live on the NAS with the generic **Questions** heading. All 524 static responses and the server-rewritten LAN/public index match the tested build. Compose commit `60ee0d09a` is pushed to the deployment repository. |
| Qualify other hosts | Six reachable hosts updated with original identities and silent startup preserved. Automated Cline question/answer canaries pass on Eagle Windows and Athena-Lpt. Eagle WSL, Pegasus Windows, Steam Deck and macbook still return an unexplained `Internal error`; fleet debugging is paused. Rocky is offline and unchanged. |
| Restore this coordinator's peer route | Complete: the supported owner-only session-agent update added `peer_messaging: true`; after the ordinary NAS restart, `sys_session_send` delivered independent peer messages and PS1 Manager replied. No scope bypass was used. |
| Run the PS1 model/effort benchmark | Five private fixtures and 92 known-good checks are pinned; the baseline rejects all five tasks. Six qualified outputs completed but none received independent acceptance scoring. Nine work cells and all ten reviews remain unrun. Incorrect-effort/setup attempts are retained separately. Pegasus is excluded for G124; Mac has no existing CMake/CTest or admitted lane. All owned benchmark sessions and processes are closed. No model-efficiency ranking is established. |
| Prepare upstream contributions | Draft [PR #10561](https://github.com/omnigent-ai/omnigent/pull/10561) supplies ACP MCP launch settings. Draft [PR #10575](https://github.com/omnigent-ai/omnigent/pull/10575) supplies structured questions and closes [#10562](https://github.com/omnigent-ai/omnigent/issues/10562), with three verified public screenshot attachments. Existing link-menu and ACP-permission contributions were corrected/rebased and validated. Upstream CI/review remain. |
| Optional OMP/Hermes layer | The documented OMP pilot still needs separate qualification of provider access, two-turn persistence and actual worker coordination. It is not on this chat's execution path. |

Suggested next replies are already implemented and deployed separately; they
remain opt-in and consume extra model usage. They are not an unfinished part
of the accepted structured-question work.

### Cline permission control, 2026-10-17

Source `db7c03010` adds **Ask every time** and **Full access** to existing
Cline/ACP composers in main, split and mobile panes. Refresh the UI and open
**Permissions** in the target chat. Selection is chat-scoped and saved only
after the runner confirms it. Full access automatically answers subsequent ACP
permission requests; explicit policy DENY/ASK still applies. Existing pending
cards need an answer. Cold runners restore the saved choice before their next
turn. No provider call or ACP process restart is needed for a live switch.

The NAS is deployed at this source, with all 525 image assets and 524 static
responses plus rewritten LAN/public index responses verified. Deployment commit
`02de0e709` is pushed to the NAS repository. Restored-database startup/restart
and rollback qualification passed; the cutover retained all 227 conversations,
102,519 existing items, the schema and all 30 other containers.

Athena's isolated runtime preserves all 91 dependency versions. After Alex
reported the old runner's rejected mode change, a fresh preflight confirmed the
host idle and its only connected chat free of pending approvals. The existing
hidden startup task activated the new host, preserving its identity. The normal
chat reconnect preserved all 138 items, and its new ACP runner confirmed the
requested **Full access** mode without sending a new provider turn. Older
runners reject the control rather than falsely saving it. Other hosts were not
restarted. Fleet troubleshooting and benchmarks remain paused.

Validation includes 241 ACP/runner tests, 43 server integration tests, 669
frontend tests, three main/split/mobile browser journeys, two real
server/runner/fixture-ACP round trips, two cold-restoration checks and 246
feature-map checks. The browser test fails against the previous deployed
bundle at the missing selector. The fixture checks are not a fresh live-provider
or human acceptance claim. The production UI build and browser journeys ran in
the bounded claimed Deck lane; its 14 owned process groups are drained and the
claim is released.

The focused upstream port is now ready for review as
[PR #10696](https://github.com/omnigent-ai/omnigent/pull/10696), closing
[issue #10695](https://github.com/omnigent-ai/omnigent/issues/10695). Its branch
`contrib/acp-session-permission-ui` at `bc5c834fe` contains the upstream desktop
and mobile controls without fork-only panes. The port passed 216 Python, 672
frontend, two browser, two fixture server/runner and 281 feature-map checks,
plus the production build and applicable hooks. Reviewed GitHub screenshot
attachments are verified by anonymous byte-for-byte download. The separate
five-minute Deck phase is drained and released. Upstream maintainer approval
remains; the earlier five open PRs have no review comments awaiting a response,
and the question-controls/MCP-launch PRs remain drafts.
