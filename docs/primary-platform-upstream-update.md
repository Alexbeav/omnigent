# Upstream update and contribution plan

Status: v0.18.0 server deployed on 2026-10-16 after Alex approved the stable target.
The isolated branch is `upgrade/v0.18-primary` in `~/Projects/omnigent-upgrade`.
Qualification and deployment results are recorded below.
The deployed application is `38f30aa96`, preserving [the primary platform work](primary-platform-plan.md).

## Recommended targets

Use release `v0.18.0` plus our required enhancements as the default deployment target.
Backport the upstream Claude request-record fix before testing this candidate.
Prepare contribution branches against current upstream `main` separately.
This separates production qualification from the contribution baseline.
Alex accepted the stable-release recommendation and authorized implementation.

| Reference | Pinned commit | Meaning |
| --- | --- | --- |
| Current fork | `b2eba8595f9c793303c7ad94cfa97ed042a2321f` | Four primary-platform commits above the earlier custom branch. |
| Current application | `2050948e3ed0bd9a93fe81974fe3ed0a56b8d2ec` | Application currently tested and deployed. |
| Latest stable | `a8676d23e88df7918f4f8ef1c7c4e3186e710354` | `v0.18.0`, released 2026-10-13. |
| Upstream main snapshot | `29ea028a590c554016dd9fee4315643e22d4a654` | Development package version `0.19.0.dev0`. |
| Common ancestor | `b05888bab8527a10e34e7c61d19f01a442ce325e` | Shared ancestor of the fork and both candidate bases. |

[Release notes](https://github.com/omnigent-ai/omnigent/releases/tag/v0.18.0)
cover Codex recovery, host reconnection, reusable agents, harness settings and Inbox changes.
Main contains 121 commits absent from the release; the release has one version commit absent from main.
These are diverged release/development histories, not a linear 121-commit upgrade.
At the pinned refs, the fork comparison is 287 upstream / 17 fork commits for stable,
and 407 upstream / 17 fork commits for main.
The 17 fork commits include 13 earlier commits and four commits from the primary-platform work.
These counts use the research baseline and exclude this plan-only documentation change.

## What the investigation established

Two `git merge-tree --write-tree` probes each reported conflicts in 16 paths.
These probes changed no branch or working-tree file.
The upstream Claude fix `35ba9e32a` also applied cleanly to stable in an alternate Git index.
That probe changed only the bridge and its upstream test file; it did not run the tests.
These checks establish mechanical applicability, not runtime compatibility.
A clean automatic merge of another file does not prove that its behavior remains correct.

The eight application/test conflicts are:

- `omnigent/inner/acp_executor.py`
- `web/src/components/chat/SideChatPane.tsx`
- `web/src/components/chat/chatBubbleParts.test.tsx`
- `web/src/pages/ChatPage.tsx`
- `web/src/shell/AppShell.tsx`
- `web/src/shell/ChatHeader.tsx`
- `web/src/shell/Sidebar.tsx`
- `web/src/store/chatStore.ts`

The remaining conflicts are two feature maps, five package/version manifests and `uv.lock`.
Use the target release's package versions and regenerate the lockfile when needed.
Do not replay the old `0.17.0` release commit or overwrite newer upstream files wholesale.

All three references contain the identical migration-directory tree
`142bd63c750feb7ae8fdce08def458f987fcfc4a`.
The parsed graph contains 112 revisions, all reachable from one head, `mm1a2b3c4d5e`.
No migration change is identified by this comparison.
A restore and application-startup rehearsal is still required because runtime storage behavior also changed.

Python remains `>=3.12`; the upstream Docker recipe uses Python 3.12, Node 22 and pnpm `11.15.1`.
The inspected direct Python SDK constraints remain unchanged apart from sibling-package release versions.
Main upgrades Pi to `1.0.4`, which requires Node `>=22.19.0`, and changes transitive dependencies.
Both the host/runner frame protocol major (`1`) and session-init protocol (`2`) remain unchanged.
These constants do not prove every old/new server-host combination works.
The captured main-check snapshot included active checks; it is not a recorded all-green qualification.

Local research evidence is under `.omnigent/verify/upstream-update-20261016/`.
It includes pinned refs, both merge probes, patch equivalence, migration graphs,
GitHub search results and the independent UI and compatibility audits.
The initial research pass ran no candidate build, restored-database test, mixed-version test or provider turn.
The implementation record below contains the later qualification results.

## Enhancement disposition and PR sequence

Upstream PRs target current `main`, use one issue per behavioral PR and follow the repository template.
The desktop pane proposal needs an issue and maintainer design discussion before a large PR.
No upstream issue, comment or PR was published during this investigation.

| Group | Deployment treatment | Upstream treatment |
| --- | --- | --- |
| Image MIME fallback | Port the filename fallback for empty/generic MIME while retaining rejection of explicit conflicting types. | A focused branch on pinned main reproduces the bug, then passes 21 attachment tests. Open [#8391](https://github.com/omnigent-ai/omnigent/pull/8391) has equivalent fallback inside a broader redesign; coordinate before submitting. [#10045](https://github.com/omnigent-ai/omnigent/pull/10045) overlaps the same files. |
| ACP agent readiness | Keep agent-specific `acp:<slug>` readiness and legacy-host unknown behavior. | Review overlap with open [#7544](https://github.com/omnigent-ai/omnigent/pull/7544). Its launch-gate alignment and our false-positive prevention need a semantic comparison. Avoid a duplicate PR. |
| Peer messaging and native grants | Preserve our same-owner authorization, provenance, loop/rate controls, and pinned-agent behavior. | Coordinate with open [#7965](https://github.com/omnigent-ai/omnigent/pull/7965) and sibling-team [#4232](https://github.com/omnigent-ai/omnigent/pull/4232). Discuss API and defaults before proposing another implementation. |
| Desktop panes and docking | Port ordered three-pane layout, draft/stream isolation, resizing, both docking directions, header actions and safe popouts. | Separate feature proposal and base layout PR. Review Canvas split-panel [#7431](https://github.com/omnigent-ai/omnigent/pull/7431) for shared layout ideas. |
| Pane configuration | Port the shared picker and explicit conversation targets after the layout. | Separate dependent PR, based on main's newer SDK reasoning-effort support. |
| Pane queue and steer | Port scoped queue operations and live-status protection after the layout. | Separate dependent PR; preserve main's mid-turn input-consumption behavior. |
| Child sidebar visibility | Port discovery/navigation into upstream's current sidebar sorting and grouping. | Independent small UI PR. Check cross-device side-chat [#10307](https://github.com/omnigent-ai/omnigent/pull/10307); ordinary child discovery is not automatically the same feature. |
| Claude request snapshots | Use upstream's broader typed-record exclusion. Stable needs that backport; main already contains it. | Do not resubmit the parser fix: [#10293](https://github.com/omnigent-ai/omnigent/pull/10293) merged on 2026-10-15. Keep additional regression coverage only if it proves a distinct boundary. |
| Old reminder text in stored bubbles | Retain the display-only workaround initially if required for this fork's old history. Never treat it as history repair. | Defer a renderer cleanup PR until a current-main reproduction exists and tests protect intentional user text containing reminder tags. The parser fix does not strip old stored bubbles. |
| Background host instructions | Keep detached launch instructions and the documented WSL lifetime distinction. | Compare existing host work [#6756](https://github.com/omnigent-ai/omnigent/pull/6756), [#8429](https://github.com/omnigent-ai/omnigent/pull/8429) and [#10292](https://github.com/omnigent-ai/omnigent/pull/10292). Avoid presenting the WSL setting as application process detachment. |

Searches identify likely overlap, not the absence of all related work.
Recheck issue ownership, existing community PRs, merge status and current main before each submission.

## Earlier fork commits: preservation ledger

For every row, record a passing behavior check and the eventual port or replacement commit.
An absent symbol or a different patch ID alone does not establish a missing behavior.

| Fork commits | Behavior to retain or replace | Current disposition |
| --- | --- | --- |
| `9e7908fb3`, `da86edcfc` | Generated ACP spawn grant and delegation guidance. | Retained; native grants, bundle composition, prompt and readiness checks pass (138 tests). |
| `304bbdf8a` | ACP permission-mode precedence and policy behavior. | Retained agent-spec precedence alongside upstream `ccaa42e92`; DENY/ASK behavior passes in the 294-test backend set. Existing Alex [#7375](https://github.com/omnigent-ai/omnigent/pull/7375) remains the contribution path. |
| `92f35bbf2` | UTF-8 host/config reads on Windows. | Retained the explicit UTF-8 reads; focused process/permission checks pass. Actual v0.18 Windows-path execution remains unproven. |
| `93eff9b2f` | Approval-mode header badge. | Retained in the current header; focused UI tests, lint, type checking and browser pane journeys pass. |
| `e20cbf347` | Docker build-context exclusions. | Retained root exclusions alongside upstream rules. The complete source build passes on BuildKit; classic-engine behavior was not rerun. |
| `a6544e17e` | Windows detached daemon survival after terminal closure. | Retained daemon-only flags. Actual Windows console closure remains separate from the passing Linux checks. |
| `8a6e5c511`, `e88754218` | ACP stalled-turn diagnostics, cancellation and wedged-session recovery. | Retained diagnostics, bounded cancellation and one-time replay while keeping upstream deleted-directory handling; backend checks pass. |
| `3c4b9c031`, `fb9a4172d`, `495202339` | Same-owner peer delivery, bounded attribution, title safety and exchange proof. | Retained; authorization, provenance, loop/rate contracts and a separate process message-and-reply journey pass. Coordinate the upstream API separately. |
| `12b5f67d2` | Old release-version edits. | Superseded by the target version. Do not port these edits. |

Alex also has open [#7370](https://github.com/omnigent-ai/omnigent/pull/7370) for absolute Windows workspaces.
Its current PR description says the earlier ACP changes already exist upstream.
Recheck the Windows-path fix independently before deciding whether the deployment fork needs it.

## Proposed implementation order

1. Pin the chosen base and create an isolated upgrade worktree and branch from it.
   Keep the deployed branch and rollback artifacts intact.
2. Reproduce the old operational behaviors against that base.
   Complete the preservation ledger before discarding any custom patch.
3. Port small independent fixes, then peer/ACP changes, then the pane layout.
   Add pane configuration and queueing with the complete UI before production qualification.
4. For a stable base, backport `35ba9e32a` and its upstream parser tests.
   Main already has this broader guard, so retain its implementation there.
5. Regenerate dependencies using the target manifests and build source and sibling SDKs together.
   Use the current `deploy/docker/Dockerfile` and record exact tool versions and artifact digests.
   The previous source-overlay image shortcut is not the default for a version upgrade.
6. Complete isolated checks, prepare the rollback package, and qualify the deployment candidate.
   Only then schedule a server cutover and a controlled refresh of idle hosts and runners.
7. After the integrated fork works, extract the independent PR branches onto current main.
   Reproduce each problem there and provide fresh proof for its final diff.

If main is selected for deployment, replace the base in step 1 with the pinned main snapshot.
Keep the same feature-preservation and validation requirements and qualify its development dependencies.
Refresh the upstream snapshot once before implementation, then keep the candidate immutable while testing it.

## Required proof before deployment

Use the current [Verify Omnigent workflow](../feature-map/skills/verify-omnigent/SKILL.md)
and read the target branch's test guide and helper catalog before adding tests.
Reuse current scenarios; add coverage only for distinct behavior or process/transport boundaries.

- Build and type/lint checks for the target branch, its SDK versions and the final frontend bundle.
- Restored Postgres copy: all original session/item identifiers, schema head, startup twice, account access and attachment references.
- Peer exchange: independent same-owner sessions, unauthorized/shared-owner rejection, attribution and loop/rate limits.
- ACP: configured and missing slugs, permission precedence, cancellation, stalled-turn recovery and fresh second turn.
- Native sessions: fresh Claude and Codex two-turn checks, resume, backend failure, child completion, provider identity and interrupted input.
- Panes: left/right order, route identity, distinct drafts/scroll/streams, correct send/model/effort/permissions, queue edit/remove/reorder/steer, two busy panes, reconnect and mobile single pane.
- Attachments: picker, paste, drop and image-only delivery with missing/generic MIME; conflicting explicit MIME remains rejected.
- Mixed versions: new server with old host, new host with old server, stale zygote fallback and a planned host refresh.
- Windows: actual terminal closure with the daemon still reachable, UTF-8 paths and native CLI configuration.

A fresh Claude process is required for the live two-turn test.
The earlier test child reused an old shared coordinator and reproduced the old defect.
Reconnecting one ordinary Claude chat does not refresh every coordinator's imported parser.
Actual OS desktop drops remain separate from the automated outside-viewport pointer check.
Queue contents are currently in memory; refresh persistence is not an implemented enhancement.
OMP placement and its three-worker proof remain deferred unless Alex brings them into this upgrade scope.

## Rollout and rollback plan

Use the homelab state and server runbook as the deployment authority when execution begins.
Read the live server pin, database head and host/session inventory again before changing anything.
The earlier inventory records seven hosts with different operating systems and installed versions.
It is not a fresh fleet-status verification for this plan.

First qualify an isolated server and host with a restored database copy and separate artifact storage.
Then test one idle host/session before scheduling the shared host refresh.
Retain the previous image, web bundle, host packages, configuration and a verified database backup.
Update only the server during its cutover and make sure that unrelated containers and Transit stay healthy.
Refresh old coordinator runners in a controlled order so their children use the new code.

If the migration graph and schema stay unchanged, use the tested application rollback path.
If implementation adds a migration, rehearse coordinated application/database rollback before release.
Do not infer that an old image alone reverses a data-format or schema change.
Update Infrastructure-State first after live changes, followed by the runbook and change log.

## Upstream submission requirements

Use current `CONTRIBUTING.md`, `AGENTS.md` and `.github/pull_request_template.md` on each PR branch.
Use fresh default-main regressions, not the old integrated fork's test totals as proof of a new PR.
Capture browser evidence for each UI diff and attach it to GitHub rather than committing demo media.
Do not include homelab addresses, local account/session identifiers, deployment backups or private logs in upstream contributions.
Keep this fork-specific plan and the operational deployment records out of those PR diffs.

## Implementation record, 2026-10-16

The candidate starts at the pinned `v0.18.0` and integrates the existing fork history.
The old `0.17.0` version edits were discarded in favor of all five v0.18 manifests and its lockfile.
The broader upstream Claude fix and its tests replace the narrower request-blob guard.
Feature-map conflicts retain upstream browser test locations and the fork feature notes.
The ACP executor keeps the upstream deleted-directory guard and the fork's stall, cancellation and one-time recovery behavior.
Frontend conflicts are resolved. Final artifact qualification and the server cutover pass. Host recovery checks pass.

Completed evidence so far:

- The isolated root package and both sibling SDKs resolve to `0.18.0` from this worktree.
- Claude bridge and transcript checks passed 509 tests.
- ACP, permission, process and peer contract checks passed 294 tests, with 9 platform/configuration skips.
- A separate peer process test passed one same-owner message-and-reply journey.
- Native grants, startup provenance and host readiness checks passed 138 tests.
- The UI passes type checking, a production build, 1,519 focused unit tests and three Chromium pane journeys.
- Mock message round trips pass with both old-server/new-host and new-server/old-host combinations.
- Host qualification exposed a same-size source rewrite that the zygote metadata guard can miss on WSL.
  The candidate adds content comparison before stale process reuse.
- The source guard passes 67 tests, and the process reaper passes 11 tests.
  Both previously affected host checks now exit zero after completing their assertions.
- Fresh isolated Claude Code and Codex subscription sessions complete two live turns each.
  Each exact user prompt appears once, with no request-snapshot or reminder-text pollution.
  This proves an ordinary follow-up on the same idle runner, not stopped-runner native transcript resume.
- The saved production snapshot restored into a private Postgres container with 95 conversations, 60,926 items and the original schema head.

The snapshot is the previously verified cutover backup, not a new live database census.
The initial development install attempted a web build while frontend conflicts remained.
The retry used `OMNIGENT_SKIP_WEB_UI=true` for the isolated test environment; the final artifact still requires the production web build.
Local evidence is under `.omnigent/verify/upgrade-20261016/`.
The serial browser rerun uses the final production bundle.
An earlier browser run overlapped its rebuild and failed before reaching two user actions.
Those setup failures do not count as feature regressions or passing evidence.
Pre-commit initially identified two effect dependencies and missing optional tracing packages.
The dependencies were corrected, and the lint environment now uses the frozen tracing extra.
Windows terminal closure, an actual OS desktop drop and a whole-fleet refresh remain separate from these Linux checks.
The first full source image passed two restored-database startups and rollback to the previous image.
All 95 original conversations, 60,926 item bodies, 19 file records and two account records remained intact.
Accounts access and anonymous rejection passed with a disposable cookie secret.
All 94 exported external Python dependency versions matched, and all 454 JS/CSS files matched the tested local bundle.
Review then tightened the image size rule: an explicit SVG MIME keeps the 5 MB limit even with a misleading PNG filename.
The final image includes that follow-up and repeats the artifact rehearsal successfully.
The following section records the later live server change.

## Live server deployment, 2026-10-16

The final application is `38f30aa96e9dfa01ebef8b6d09e2e19a2696fd23`.
The image pin is `registry.crosstalkis.com/omnigent-server:sha-38f30aa96@sha256:c0b9ea754533c54c5c8c0293007cd429c829051efbaf6b6ddd0236ac789b7cd0`.
The server and both sibling SDKs report `0.18.0`.
The image uses the complete upstream Docker recipe with all 94 external runtime requirements frozen and checked.
All 454 served JS/CSS files match the final tested local bundle.
The final UI proof passed nine pane/attachment journeys and six picker/paste/drop image-send journeys.

The rollback-aware cutover stopped and recreated only `omnigent`.
It retained all 96 conversations and 61,863 original item IDs with zero missing originals.
One new item arrived after restart, and the schema stayed at `mm1a2b3c4d5e`.
Accounts access, anonymous rejection and the active chat's history read pass.
The server is healthy with zero restarts; Postgres and 30 other containers retained their IDs, starts and restart counts.
Transit Vault remains healthy and unsealed.

Backup and rollback package: `/volume1/docker/stacks/omnigent/backups/upgrade-v018-20261016-38f30aa96/`.
The verified quiescent dump is 58,222,044 bytes, SHA-256 `e35abf564b5183502a8cbb9f4bc002c0fef78742fb09e74cdd6de14be62c9a22`.
The saved Compose pins the previous `2050948e3` image.
The isolated rehearsal established rollback with this unchanged schema.
The live Compose pin is committed locally on the NAS as `eb7825598` and is not pushed.
The unrelated monitoring edit remains untouched.

The existing shared host, zygote, installed host packages and coordinator runners remain unchanged during active work.
Fresh isolated candidate providers pass ordinary two-turn checks, but that does not refresh existing production adapters.
A unique temporary v0.18 host then ran fresh Claude and Codex chats against the production server.
Both completed two real subscription turns, and each exact user prompt appeared once without reminder pollution.
Both proof chats were archived, and the owned host process was stopped.
The server exposes no supported unmanaged-host deletion API, so its offline canary row remains.
That proof covers ordinary follow-ups on the same idle runner, not native transcript recovery after process replacement.
A full fleet refresh, actual Windows console closure, real OS desktop drops and OMP acceptance remain outside this server result.
The current host presence and operational authority remain in the homelab Infrastructure-State note.

Reload with Ctrl+Shift+R, dock a chat on each side, and change the model and reasoning in one secondary pane.
Queue and steer a follow-up there, then attach an image through the picker or clipboard.
The primary pane's draft and model must remain unchanged.

The first focused upstream candidate is `contrib/image-mime-fallback` on pinned main, committed as `97a57e7f0`.
Its 21 attachment tests pass after reproducing the original failure.
Open #8391 has direct semantic overlap, so no duplicate PR is published.

## Host upgrades and silent sign-in startup, 2026-10-16

Alex selected automatic startup at sign-in without a visible terminal or browser.
Five idle hosts now run the qualified application `38f30aa96`, with Omnigent and both SDKs at `0.18.0`.
Each retains its original production host ID and reports online.
The server image and database were unchanged by this host rollout.

| Host | Installed runtime and startup |
| --- | --- |
| Eagle native Windows | Separate frozen environment, enabled `OmnigentHostV018` sign-in task and hidden waiting WScript supervisor. |
| Pegasus native Windows | Same isolated environment and task model as Eagle native Windows. |
| Pegasus WSL | Separate frozen environment, existing enabled systemd user service with lingering, and hidden Windows keepalive task. |
| Steam Deck | Updated uv tool from pinned source, enabled systemd user service with lingering and explicit Node PATH. |
| Pacifica / macbook | Updated uv tool from pinned source, canonical `ai.omnigent.host` LaunchAgent, Node PATH and Intel `cryptography<49` constraint. |

The native Windows hosts retain their old global v0.17 CLI and legacy task backups.
Pegasus WSL retains its old global v0.13 CLI and saved unit.
Read the selected service executable's package metadata rather than the legacy command on PATH.
Pacifica's legacy plist is outside `LaunchAgents`, so it cannot create a duplicate at the next sign-in.
The [Windows installer and rollback helpers](../deploy/hosts/windows-signin/README.md) preserve old checkouts and global tools.
The [background-host guide](background-hosts.md) explains the platform startup models.

Eagle WSL has a separate pinned v0.18 environment and an enabled hidden sign-in task.
Its launcher's manual test returned success after detecting the healthy existing v0.17 daemon.
The shared host and zygote remain alive, so this upgrade does not interrupt the active chat.
The new environment activates after a cold start or an explicit idle handoff.
No WSL systemd setting or existing SSH service changed.

Rocky remains offline and was not upgraded.
Its stale DNS and SSH address reaches the Windows laptop instead, proven through existing Windows SSH trust.
No host key, DNS record or SSH configuration changed.
The earlier Cline/OMP fleet acceptance remains deferred.

Final read-only checks show all six reachable original hosts online and the server healthy.
Package provenance, service ownership and Windows process chains were checked.
The hidden launchers request window style 0, and the inspected processes have no main window handle.
A physical sign-out/sign-in cycle and provider turns on the upgraded hosts remain untested.
At the next convenient sign-in, make sure that no empty terminal or browser opens.
Open Omnigent on the phone, make sure that the intended hosts return online, and send a small message through a configured provider.
Private execution reports, rollback paths and sanitized checks are under `.omnigent/verify/host-upgrade-20261016/`.
The homelab Infrastructure-State note and host-upgrade runbook remain the operational authority.
