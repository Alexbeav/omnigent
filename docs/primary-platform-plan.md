# Omnigent primary platform work

This record covers Alex's five requests from 2026-10-15 and the later child-chat visibility report.
The starting revision is `e88754218` on `feature/session-orchestration-v0.17`.
The integrated work is on the local branch `feat/primary-platform` in `~/Projects/omnigent-primary`.
The live editable checkout remains `~/Projects/omnigent`.

## Result by request

| Request | Implemented or established | Limit |
| --- | --- | --- |
| Independent chat messaging | Generated native agents receive the existing same-owner peer grant. Native startup instructions identify messages from other agents. | Existing sessions retain pinned definitions. Deploy the changes and start or update agent definitions before live use. |
| Web pictures | Shared validation accepts supported image filenames when browser MIME data is empty or generic. Sending uses an image content block. | The exact cause of the original interface report remains unconfirmed. Live vendor image turns were not tested. |
| Three tall chats | Three desktop columns, add control, sidebar edge-drop, resizing, separate drafts and sends, popout, and close/reopen. | Widths are not saved after reload. Dragging outside the page does not create a window. |
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

## Rollout boundary

The code has not been deployed to the NAS server or the live host checkout.
No database migration or authentication change is part of this patch.
Build and pin a new server image from the reviewed branch, then update compatible hosts.
Preserve the current image and data for rollback.
Avoid restarting the host that owns active work until those sessions can tolerate a disconnect.
Validate new native agent definitions with disposable chats before changing existing long-running sessions.
