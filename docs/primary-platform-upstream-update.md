# Upstream update and contribution plan

Status: v0.18.0 server deployed on 2026-10-16 after Alex approved the stable target.
The isolated branch is `upgrade/v0.18-primary` in `~/Projects/omnigent-upgrade`.
Qualification and deployment results are recorded below.
The upgrade records below describe earlier snapshots. The current complete-source
deployment and owner setup steps are recorded in [the primary platform plan](primary-platform-plan.md#suggested-replies-2026-10-16).

## Contribution status checked on 2026-10-16

The chat-link context menu is submitted as [PR #10492](https://github.com/omnigent-ai/omnigent/pull/10492),
closing [feature issue #10490](https://github.com/omnigent-ai/omnigent/issues/10490).
Branch `contrib/chat-link-menu`, head `f4dc0ec52`, starts from upstream `ce8066dd7`;
it contains only the link menu, shared opening helpers, focused tests and feature-map update.
It passes 95 component checks, eight Chromium browser-contract journeys, 266 feature-map checks,
build, types, documentation links and applicable pre-commit hooks.
The four new menu regressions fail against unchanged upstream code.
The browser journeys cover actual clipboard writes, new tabs and popup fallback;
desktop routing uses a simulated bridge and does not establish native OS browser behavior.
The Demo section embeds the sanitized capture uploaded through GitHub's PR editor.
The PR is ready for review; maintainer approval is required. No demo media is committed.
Private evidence is under
`~/.local/state/omnigent-investigations/link-menu-upstream/`.
Maintainer [PR #9910](https://github.com/omnigent-ai/omnigent/pull/9910) overlaps in the renderer,
but adds Copy path rather than the browser choices or navigable file-preview URL.
Both the issue and PR describe that overlap for rebase coordination.

Child-chat sidebar visibility is submitted as [PR #10431](https://github.com/omnigent-ai/omnigent/pull/10431), closing [feature issue #10430](https://github.com/omnigent-ai/omnigent/issues/10430).
Its isolated branch `contrib/sidebar-child-chats` starts at upstream snapshot `b6119bb8470624d22cc142691871dba155e75063`.
The focused head is `0400f473279b0e43676aa573d1a8de6a9904789b`, with no deployment records or unrelated fork enhancements in the diff.
The branch passes 177 component checks, its isolated browser journey, 264 feature-map checks, lint, type checking, build and pre-commit.
Alex attached the sanitized screenshot, and the Demo section now embeds it. PR #10431 is ready for review.
Maintainer approval is still required. No demo media was committed to the repository.

The pane proposal is [#10429](https://github.com/omnigent-ai/omnigent/issues/10429).
A [coordination comment on #6758](https://github.com/omnigent-ai/omnigent/pull/6758#issuecomment-6211218243) explains the narrower three-column workflow and planned contribution sequence.
The existing split-workspace implementation is broader, so the large layout PR waits for that design coordination.
The tested fork remains available and deployed while that discussion proceeds.

The [Windows workspace PR #7370](https://github.com/omnigent-ai/omnigent/pull/7370) is closed as superseded by merged [#7837](https://github.com/omnigent-ai/omnigent/pull/7837).
Current main uses `isHostAbsolutePath` for the submit gate and deliberately rejects backslash UNC paths, matching server validation.
The original ACP model fixes are also upstream. The old branch and its unsigned historical commit remain intact.
The broader Windows issue #2422 remains open.

The [ACP permission PR #7375](https://github.com/omnigent-ai/omnigent/pull/7375) remains open.
All 61 reported check runs were inspected: Maintainer Approval fails, while DCO and the reported tests pass.
Those are existing results, not a new maintainer review or fresh current-main compatibility proof.

Upstream merged the [Claude transcript fix #10293](https://github.com/omnigent-ai/omnigent/pull/10293) and [ACP readiness map #7544](https://github.com/omnigent-ai/omnigent/pull/7544).
Compare any additional create-time readiness guard separately before proposing it.
The image fallback branch passes its recorded focused checks, but [#8391](https://github.com/omnigent-ai/omnigent/pull/8391) still has direct overlap.
Coordinate the peer-message API and attachment overlap before publishing competing implementations.
The Firefox bridge is a local MCP integration and adds no application patch to submit.
Private refreshed API snapshots are under `.omnigent/verify/upstream-ready-20261016/`.
The child contribution evidence is under `~/Projects/omnigent-contrib-children/.omnigent/verify/upstream-child-sidebar-20261016/`.

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
| ACP agent readiness | Keep agent-specific `acp:<slug>` readiness and legacy-host unknown behavior. | [#7544](https://github.com/omnigent-ai/omnigent/pull/7544) merged at `2026-10-15T23:58:57Z`. Compare the new readiness-map behavior with our additional create-time guard before proposing any remaining change. Avoid a duplicate PR. |
| Peer messaging and native grants | Preserve our same-owner authorization, provenance, loop/rate controls, and pinned-agent behavior. | Coordinate with open [#7965](https://github.com/omnigent-ai/omnigent/pull/7965) and sibling-team [#4232](https://github.com/omnigent-ai/omnigent/pull/4232). Discuss API and defaults before proposing another implementation. |
| Desktop panes and docking | Port ordered three-pane layout, draft/stream isolation, resizing, both docking directions, header actions and safe popouts. | Separate feature proposal and base layout PR. Review Canvas split-panel [#7431](https://github.com/omnigent-ai/omnigent/pull/7431) for shared layout ideas. |
| Pane configuration | Port the shared picker and explicit conversation targets after the layout. | Separate dependent PR, based on main's newer SDK reasoning-effort support. |
| Pane queue and steer | Port scoped queue operations and live-status protection after the layout. | Separate dependent PR; preserve main's mid-turn input-consumption behavior. |
| Child sidebar visibility | Port discovery/navigation into upstream's current sidebar sorting and grouping. | [#10431](https://github.com/omnigent-ai/omnigent/pull/10431), closing [#10430](https://github.com/omnigent-ai/omnigent/issues/10430), passes focused current-main checks. The sanitized demo is attached, and the PR is ready for review. Cross-device side-chat [#10307](https://github.com/omnigent-ai/omnigent/pull/10307) remains a separate feature. |
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

Earlier Windows workspace PR [#7370](https://github.com/omnigent-ai/omnigent/pull/7370) is now closed as superseded by #7837.
The ACP model-selection paths also already exist upstream.
Current main deliberately rejects UNC workspace paths, matching server validation.

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

Eagle WSL now runs the separate pinned v0.18 environment after Alex completed the manual idle handoff.
The original host ID reports online, with one candidate daemon and all three packages at `0.18.0`.
The old host and zygote are gone, and the hidden sign-in task is enabled and running.
This chat continues to accept messages after the change.
No WSL systemd setting or existing SSH service changed.

Rocky remains offline and was not upgraded.
Its stale DNS and SSH address reaches the Windows laptop instead, proven through existing Windows SSH trust.
No host key, DNS record or SSH configuration changed.
The earlier Cline/OMP fleet acceptance remains deferred.

Final read-only checks show all six reachable original hosts online on v0.18 and the server healthy.
Package provenance, service ownership and Windows process chains were checked.
The hidden launchers request window style 0, and the inspected processes have no main window handle.
A physical sign-out/sign-in cycle and provider turns on the upgraded hosts remain untested.
At the next convenient sign-in, make sure that no empty terminal or browser opens.
Open Omnigent on the phone, make sure that the intended hosts return online, and send a small message through a configured provider.
Private execution reports, rollback paths and sanitized checks are under `.omnigent/verify/host-upgrade-20261016/`.
The homelab Infrastructure-State note and host-upgrade runbook remain the operational authority.

## Firefox integration, 2026-10-16

The [Firefox guide](primary-platform-browser.md) records the local MCP connection for Omnigent web.
FoxPilot uses the existing Windows Firefox profile through native Windows Node and a loopback broker.
Eagle WSL Codex, Claude Code and Cline user MCP configurations point to the pinned `1.0.29` server.
Private backups preserve the original configurations, and unrelated settings remain intact.
Alex installed the signed Firefox add-on, and direct page reading passes after domain consent.
A fresh native Codex chat calls FoxPilot and receives the active Firefox result.
Alex enabled Automation Mode and its one-time all-websites grant.
The existing native Codex chat passes a new-domain page read, snapshot, typing, click and screenshot without another domain-permission error.
The owned test tab was closed, and no external form was submitted.
Claude/Cline browser turns and persistence across a Firefox restart remain unproven.
This configuration change requires no server image or web bundle rebuild.

## Split preview and active-pane follow-up, 2026-10-16

The separate right-edge window drop target is removed.
Each chat's left and right halves now show a blue-outlined, blurred split preview on hover.
The header popout buttons and supported outside-page releases still request a separate window.
Clicking or focusing a chat marks its pane active.
A plain sidebar session click replaces that pane and retains the other chats, drafts, positions and divider widths.
Choosing an already-open chat focuses its pane without duplication.
Mobile single-chat navigation and modified browser clicks retain their normal paths.

The focused shell component suite passes 192 tests.
The isolated browser journey covers preview geometry, both directions, reordering, the three-chat limit, cancellation, popouts and active-pane replacement.
Its primary and secondary replacements retain the other drafts, restore a replaced draft and keep the divider positions.
All three browser journeys pass, including per-pane model, permission, queue and steer controls.
Desktop slot widths apply only from 768 pixels upward, so a reordered primary chat fits the phone viewport.
The browser regression first reproduced a 479-pixel pane on a 390-pixel screen, then passed with the responsive width rule.
Frontend lint, type checking, pre-commit hooks and 231 feature-map contract tests pass.
The [pane guide](primary-platform-panes.md) contains human verification steps.
Private browser captures and validation logs are under `.omnigent/verify/drag-preview-20261016/`.

## Split preview release deployed, 2026-10-16

The private production server runs v0.18.0 with UI source `b68236eee53057e3d7242c5fd9cf835cb7227477` on `upgrade/v0.18-primary`.
The image is `registry.crosstalkis.com/omnigent-server:sha-b68236eee@sha256:4a99da03186bda1c8deec4e047796872ee666ee68e80bfad11b81871222eb8d0`.
This UI release reuses the qualified `38f30aa96` runtime. All 919 Python source files and 98 installed package versions match that runtime.
All 525 packaged web assets match the tested build, and all 454 served JS/CSS files match by SHA-256.
The entry bundle is `assets/index-Ban-Pc5n.js`.

The final release passes 192 component tests, three Chromium journeys, 231 feature-map contract tests, type checking, lint, build and pre-commit.
The browser journey also moves the primary into a resized slot before switching to the phone viewport.
Canonical HTTPS health, anonymous HTTP 401 and existing-account session/history reads pass without an OAuth refresh.
Cutover retained all 113 conversations and 64,829 original item IDs, with zero missing IDs and schema `mm1a2b3c4d5e` unchanged.
Two new items arrived after restart, so the immediate after count was 64,831.
Only `omnigent` changed. Postgres and all 30 other container records retained their IDs, start times, status and restart counts.
The server is healthy with zero restarts, and Transit remains unsealed.

The fresh dump is `/volume1/docker/stacks/omnigent/backups/split-active-20261016-b68236eee/cutover.dump` (64,456,562 bytes, SHA-256 `ed13c5c7dd37d2618645504dbb1582961ec3062169a1efcc7e90711554480366`).
The directory retains the previous Compose file, deployment result and rollback-aware script.
The prior UI image `f0f7ee0e3` and its separate backup remain available too.
The NAS Compose pin is local commit `7eb5e2f2dba53904679b23cc78cbde29eecb51bb` and is not pushed.
The monitoring edit remains untouched. No provider host or browser profile was restarted.
Private evidence: `.omnigent/verify/drag-preview-20261016/verification.md`, `candidate.json`, `deployment.json` and `live-verification.json`.
Human steps are in the [pane guide](primary-platform-panes.md#human-verification).
Upstream PR submission remains deferred until this UI follow-up is tested by Alex.

## Divider regression follow-up, 2026-10-16

The resize handles previously belonged only to secondary chats.
A secondary-primary-secondary layout therefore had a handle at the outer left edge and none between the first two chats.
The existing browser journey reproduces the missing primary divider against the deployed bundle.

Every gap now has a shared resize handle, independent of the chat's role.
A drag or Left/Right key changes only the adjacent pair and leaves the third chat's width fixed.
Both neighbors retain a 320-pixel minimum, and slot sizes still survive a sidebar replacement.
The browser regression exercises both handles with the primary on the left, in the middle and on the right.
The component cases cover the same three orders, along with the minimum-width boundary.
All 195 focused component tests and three browser journeys pass, along with 231 feature-map contract tests.
Final logs and recordings are under `.omnigent/verify/pane-resize-20261016/`.

Deployed from `dcf3a29e93671be9f4f995d43b86759b0bd3aa73` on `upgrade/v0.18-primary`.
The immutable image is `registry.crosstalkis.com/omnigent-server:sha-dcf3a29e9@sha256:9790c8ea83c41b6ac04a37ce52e4a27a5dea18c74a848b1608b17d6b0ce4497f`.
The runtime remains v0.18.0 with the same 919 Python source files and 98 installed packages as qualified `38f30aa96`.
All 525 packaged assets match the tested build. All 454 served JS/CSS files match by SHA-256, with entry `assets/index-CDOfLwSK.js`.
Canonical HTTPS health, anonymous HTTP 401 and existing-account session/history reads pass without OAuth refresh.
Cutover retains all 117 conversations and 65,946 original item IDs, with zero missing and schema `mm1a2b3c4d5e` unchanged.
Two new items arrived after restart, so the immediate after count was 65,948.
Only `omnigent` changed. All 30 other container records remain unchanged, the server is healthy with zero restarts, and Transit remains unsealed.

Fresh backup: `/volume1/docker/stacks/omnigent/backups/pane-resize-20261016-dcf3a29e9/cutover.dump` (66,506,972 bytes, SHA-256 `31157925785a6cddcd83b5864aa50452bc5d4047d100aa6e5ca3830bde511607`).
The previous image, Compose file and rollback-aware script remain available.
The Compose pin is local NAS commit `ffb1a78962a9ea72960f5526cbfd797e8934ece8` and is not pushed.
The monitoring edit and provider hosts remain untouched.
Private evidence: `.omnigent/verify/pane-resize-20261016/verification.md`, `deployment.json` and `live-verification.json`.
To test, refresh the browser, drag each divider in both directions, then move the primary chat and repeat.

## Equal pane controls and project creation, 2026-10-16

The full toolbar now follows the selected chat above the desktop columns.
Share, session menus, agent information, Terminal, and Workspace actions use that session.
Selecting another pane updates the route while the chat surfaces retain their drafts and scroll state.
Only the shell binds the selected session stream, which avoids competing bindings during startup.

New-session navigation replaces only the selected slot, including project buttons and menus, sidebar New session, shortcut, and command palette.
A new chat that finishes in the background fills its original slot without stealing the current selection.
A failed creation restores the unsent prompt in that slot.
Ordinary split panes also load earlier history for their own session and preserve the reading position.
The native terminal view belongs to its pane, and Chat restores its composer.

The existing browser scenarios now exercise the selected-session route with stable pane selectors.
The new creation variants reuse the browser session fixture and explicit session, project, sharing and event-stream contracts.
The local hostname alias permits Share in the isolated browser without a real account or external request.
The contracts cover foreground creation, background creation, and failure, with one initial send only on success.
Private evidence is under `.omnigent/verify/active-pane-controls-20261016/`.
Upstream PR publication remains deferred for Alex to test this UI follow-up.

Qualification passed 964 component checks, 746 history/store/pane checks, and 654 final creation/pane/terminal checks.
Feature-map contracts pass 232 tests. The production build, frontend lint, type checking, documentation links and pre-commit pass.
A background failure regression also confirms that the restored composer does not steal selection through automatic focus.
The inactive shell-close regression confirms that closing its shell does not change the selected chat view.

All six isolated Chromium journeys pass against the final rebuilt UI in 38.89 seconds. Final recordings and captures are under `.omnigent/verify/active-pane-controls-20261016/browser-qualified/`.

Deployed UI source `23fa269450e7833d0cb345045e1cbfff4296f2bf` from `upgrade/v0.18-primary`, pushed to Alex's fork.
The immutable image is `registry.crosstalkis.com/omnigent-server:sha-23fa26945@sha256:88a170a1d2d05ef02bf5f1fa58914625f7474daaf3a7c7286ac691abbeb3f473`.
The runtime remains v0.18.0, with all 919 Python source files and 98 installed packages identical to qualified `38f30aa96`.
All 525 packaged assets match the tested build. All 454 served JS/CSS hashes match, with entry `assets/index-D8GFdTyl.js`.
Canonical HTTPS health, anonymous HTTP 401 and existing-account session/history reads pass without OAuth refresh.
Cutover retains all 122 conversations and 68,077 original item IDs, with zero missing and schema `mm1a2b3c4d5e` unchanged.
Only `omnigent` changed. All 30 other container records remain unchanged.
The container is healthy with zero restarts. Transit remains initialized and unsealed.
Fresh backup: `/volume1/docker/stacks/omnigent/backups/active-pane-controls-20261016-23fa26945/cutover.dump` (69,976,334 bytes, SHA-256 `43365ec03095f7bae64c365d87b76570af001779ee1d8244fae33edd3dbe7433`).
The previous image, Compose file and rollout script remain available for rollback.
The NAS Compose pin is local commit `de7d20d63df0999bbaa76643eb9dab949245b4df` and is not pushed. The monitoring edit and provider hosts remain untouched.
Infrastructure state was updated first, followed by the server plan and monthly change log.
Private qualification, deployment and live-verification records remain in `.omnigent/verify/active-pane-controls-20261016/`.
To test, refresh with Ctrl+Shift+R, select each pane and open Share or Workspace, then start a project chat in the middle slot.
The toolbar must follow the selection, and the other two chats and their drafts must remain.

## Stopping point, 2026-10-16

Alex confirmed the deployed UI works and requested no further development until a new idea or an update check.
The application source is committed on `upgrade/v0.18-primary` and pushed to `Alexbeav/omnigent`.
The deployed UI source remains `23fa269450e7833d0cb345045e1cbfff4296f2bf`; later commits record deployment and contribution status only.
The independent child-sidebar contribution is pushed as `contrib/sidebar-child-chats` at `0400f473279b0e43676aa573d1a8de6a9904789b`.
Both working trees were clean and their remote branch heads matched before this documentation closeout.

Alex supplied the screenshot on #10431. Its Demo section now embeds the attachment, and the PR is ready for review.
The existing maintainer-approval requirement remains. The pane proposal #10429 awaits coordination with #6758.
No further development, host upgrade, deployment, or automatic update check is scheduled.
Resume only when Alex requests more work or an update check.

Deployment, rollback and verification facts remain in this record and the homelab Infrastructure-State note, server plan and monthly change log.
The NAS Compose configuration is commit `de7d20d63df0999bbaa76643eb9dab949245b4df`, pushed to `Alexbeav/homelab-ulduar` main on 2026-10-16 at Alex's request.
Credentials, database backups, raw logs and temporary demo captures remain outside the application Git history.

## NAS deployment repository push, 2026-10-16

Alex requested the NAS deployment push after the application closeout.
All eight pending Omnigent deployment and HTTPS commits are pushed to `Alexbeav/homelab-ulduar` main.
The remote head matches `de7d20d63df0999bbaa76643eb9dab949245b4df`.
The commits change only the deployment README, Omnigent example environment values, and the Omnigent Compose file.
The push used normal history advancement. The live Compose file and uncommitted monitoring edit remain unchanged.
No service was restarted. Infrastructure state was updated before the server plan and monthly change log.
Private verification is under `.omnigent/verify/nas-deployment-push-20261016/`.

## Question-controls rollout and contributions, 2026-10-17

Application source `910495755434bb66348afcdb25d1d325cd4b73ba` is deployed to
the NAS. The immutable image is
`registry.crosstalkis.com/omnigent-server:sha-910495755@sha256:878b9d527a0fb964b785805ba89559f360b04fefe7b0293f8b3f46f132dd58f0`.
It carries the seven changed Python files and a fresh 525-file web build over
the previous frozen image. Dependencies and migrations are unchanged. The generic
**Questions** heading is now served; all 524 static responses match their build
hashes, and LAN/public index responses match the server's base-path rewrite.

An isolated restored database preserved conversation, item, account and file
fingerprints across two candidate starts and a rollback to the old image. All 98
dependency distributions matched. Production cutover retained all 195
conversations and 83,991 original items, with zero missing identifiers and schema
`mm1a2b3c4d5e` unchanged. All 30 other containers retained their identities, start
times and states. The private backup and rollback Compose file are under
`/volume1/docker/stacks/omnigent/backups/question-controls-20261017-910495755/`.
The dump is 100,431,756 bytes, SHA-256
`c7cadb363bb6e33de336c5fa70f69cd65607c2851281aed2b274f3c1845faf23`.
Deployment commit `60ee0d09a3a4b994089f0295ae0f2a0e76e7a5e6` is pushed to
`Alexbeav/homelab-ulduar` main; the monitoring edit is preserved.

Six reachable idle hosts now use the pinned source with original host identities
and silent startup preserved: Eagle Windows, Eagle WSL, Pegasus Windows,
Athena-Lpt, Steam Deck and macbook. Pegasus WSL's working `0d3c2686` host was
not restarted. Rocky remains offline and unchanged. All six updated hosts report
Cline 3.0.72, but only Eagle Windows and Athena-Lpt passed automated
question/answer/acknowledgement canaries. Athena required **Allow once** under its
existing permission mode. The other four returned an unexplained
`inner executor error: Internal error` before posting questions; authentication
failure is not established. All 11 owned fleet test chats are stopped and
archived. Fleet debugging is paused, with successful changes and rollback
receipts preserved. These synthetic checks are separate from Alex's earlier
human acceptance on this coordinator's host.

The coordinator's original user-agent bundle was updated through the supported
owner-only session-agent API, adding only `peer_messaging: true`. Following the
normal NAS restart, the same `sys_session_send` tool delivered independent peer
messages, and PS1 Manager replied with task constraints and resource guidance.
No alternate dispatch route, direct database edit or scope bypass was used.

The private five-task benchmark has a rejecting baseline and 92 passing
known-good checks. Partial work outputs and provider usage are retained, including
workspace-placement failures and turns whose actual native effort was `xhigh`
instead of requested low/high. Those turns are excluded from the comparison.
Further Pegasus benchmark work is excluded while G124 needs its memory. Mac
preflight found no existing CMake/CTest or admitted lane, and the manager requested
an explicitly incomplete matrix. No Mac tool installation, provider turn or
compiler run was made. No model-efficiency ranking or completed review gauntlet
is claimed.

The final partial report records six qualified, unscored outputs: four Cline and
one each at verified GPT low/high. Nine work cells and all ten reviews remain
unrun. All 16 benchmark chats are stopped and archived, transcripts exported,
and all 82 receipt-matched residual processes are gone, including 75 directly
signalled PIDs. The shared host and coordinator remain running. Windows had
5.48 GiB available, below the manager's 8 GiB gate; no cache/VM changes or
unrelated process kills were made. The complete private report is
`omnigent-benchmark-20261017/results/final-partial/FINAL-MATRIX-SO-FAR.md`.

Focused contributions were ported to current upstream without fork-only docs or
pane dependencies:

| Contribution | Publication and validation |
| --- | --- |
| ACP per-chat MCP launch settings | Draft [PR #10561](https://github.com/omnigent-ai/omnigent/pull/10561), branch `contrib/acp-mcp-launch-settings`, source `bc9c3a800`. 166 tests and applicable pre-commit hooks passed. |
| Structured question controls | Draft [PR #10575](https://github.com/omnigent-ai/omnigent/pull/10575), branch `contrib/structured-question-controls` at `3ebc6ad4a`, closes [issue #10562](https://github.com/omnigent-ai/omnigent/issues/10562). 1,179 backend/E2E/map checks, 657 frontend tests and six browser journeys passed. All three reviewed screenshots are embedded as real GitHub attachments, with anonymous downloads verified byte-for-byte. No media was committed. |
| Link-menu browser fixture correction | [PR #10492](https://github.com/omnigent-ai/omnigent/pull/10492), source `d4f45d5b0`. Both previously failing browser cases pass after fixing the response fixture and strengthening the page-error assertion. |
| ACP permission-mode rebase | [PR #7375](https://github.com/omnigent-ai/omnigent/pull/7375), source `50148ff45`. 233 focused checks and applicable hooks passed before an exact-lease push. |

[PR #10431](https://github.com/omnigent-ai/omnigent/pull/10431) still needs
maintainer review/approval. The pane proposal
[issue #10429](https://github.com/omnigent-ai/omnigent/issues/10429) still overlaps
[PR #6758](https://github.com/omnigent-ai/omnigent/pull/6758); no competing pane PR
was opened. Local test results do not claim all GitHub CI gates have passed.
No GitHub comments or merges were made in this contribution pass.

To verify the deployed UI, refresh it and request a fresh structured question in
a working provider chat. Select an option and submit; the answer must reach that
source chat. To enable optional next replies, choose **Settings → General →
Composer → Suggest my next reply** in each browser. Leave the active empty
composer focused after a new native Codex/Claude reply, then press **Tab** or
**Right Arrow** to accept the suggestion into an editable draft. Acceptance never
sends it. This adds model usage and does not support Cline yet.

Operational state was updated first in the homelab Infrastructure-State note,
then the server plan. The monthly change-log file returned a OneDrive I/O error
and was left intact. Private execution/rollback evidence remains under
`~/.local/state/omnigent-investigations/rollout-20261017/`; benchmark fixtures,
raw transcripts, credentials and demo media remain outside the application Git
history.

### Cline composer permissions follow-up, 2026-10-17

Fork source `db7c03010` adds a per-chat permission selector for existing ACP
chats, including Cline. It exposes **Ask every time** and **Full access** in
main, split and mobile composers, confirms the runner's exact acknowledgement
before persistence and restores the choice before a cold runner's next turn.
Explicit policies retain precedence. The focused upstream port is ready for
review as [PR #10696](https://github.com/omnigent-ai/omnigent/pull/10696), closing
[issue #10695](https://github.com/omnigent-ai/omnigent/issues/10695). Source
`bc5c834fe` is pushed to `contrib/acp-session-permission-ui`, based on upstream
`90a9bed9a`. It does not include the fork's ordinary split-pane code and is
independent of the existing per-agent configuration PR #7375.

The upstream port passed 216 focused Python checks, 672 frontend checks, two
desktop/mobile browser journeys, two real server/runner/fixture-ACP journeys,
281 feature-map checks, a production Vite build and all applicable pre-commit
hooks. The two reviewed screenshots are GitHub attachments; anonymous downloads
match their captured bytes. No media is committed. The bounded Deck validation
phase finished within five minutes, all four receipt-matched process groups
were drained, and its unique claim was released.

All five earlier open PRs were checked for comments, reviews and unresolved
threads: none has maintainer feedback awaiting a response. #10431 contains only
the author's earlier demo comment. #10561 and #10575 remain drafts. The older
Windows PR #7370 stays closed because its remaining fix is already upstream.
The new PR's DCO check passes; GitHub's separate maintainer-approval gate awaits
an upstream maintainer. Local validation does not claim all remote CI passed.

The NAS now runs
`registry.crosstalkis.com/omnigent-server:sha-db7c03010-r2@sha256:98d75f43e43474762a56c45d7427309408e098e6bf361bf598541dac89f26684`.
Two isolated candidate startups and an old-image rollback preserved original
rows and all 98 dependency distributions. The live cutover retained all 227
conversations and 102,519 existing items; no other container changed. All 525
packaged assets and 524 static responses plus the server-rewritten LAN/public
index match the tested build. NAS deployment commit `02de0e709` is pushed.

The verified private dump is
`/volume1/docker/stacks/omnigent/backups/acp-permissions-20261017-db7c03010-r3/cutover.dump`,
129,396,836 bytes, SHA-256
`7458bb78e57e155f672eb6cf6677a034f5c06340b6cd47ac4e1bc4e64edafc23`.
Athena is active on its isolated qualified runtime after a fresh idle-host
preflight. Its hidden task and host identity are preserved. The manager chat's
new ACP runner confirmed the requested **Full access** mode, preserving all
138 stored items without a new provider turn. Its original installation remains
intact for rollback. Other hosts were not restarted.
Deployment evidence is under
`~/.local/state/omnigent-investigations/acp-permissions-20261017/`.

### ACP working notes, 2026-10-17

Alex selected collapsed narration with a visible final reply. Source
`a9366665858fe3976cb0eb84ffbd475df25502b1` is pushed to all three fork branches and deployed as
`registry.crosstalkis.com/omnigent-server:sha-a93666658@sha256:663ec1a2fa757a072ab81e34378b9713a87caed64012058b1ee56be7a3e5e91d`.
The shared web renderer collapses ordinary ACP narration into expandable
**Working notes**, revealing the final text run when the turn settles. Stored
history, model input and native reasoning transport are unchanged. Questions,
approvals, errors and tool controls remain available. Main, split and mobile
browser checks pass; 781 component/store tests, 248 feature-map checks, the
production build and pre-commit pass. Two regression cases fail with the
original renderer. Browser proof uses a mocked backend, not a live-provider
completion. A provider that mixes narration directly into its last text run
retains that complete run as its visible reply. See the
[working-notes recipe](../feature-map/working-notes.md).

Two isolated candidate starts and an old-image rollback preserved original
rows and all 98 dependency distributions. The live switch preserved all
227 conversations and 104,110 existing items;
all 30 other containers were unchanged. All 525 packaged
assets and 524 static responses plus rewritten LAN/public indexes match the
tested build. The backup is `/volume1/docker/stacks/omnigent/backups/cline-notes-20261017-a93666658/cutover.dump`,
132,161,754 bytes, SHA-256 `3c83832a038e0184a791974394aa2c2846714b43b491ac62401a4cd600be67da`.
NAS Compose commit `a7fcb14f3308e7ec0949a2720a06b5b985b6caef` is pushed. Athena needed no host or runner
restart. Both bounded Deck phases are drained and exact claims released;
the first phase's incorrect fixture order is retained as failed-test evidence.
Fleet troubleshooting and benchmarks remain paused. Source and deployment
receipts are in `~/.local/state/omnigent-investigations/cline-reasoning-20261017/`;
browser captures and process receipts are in the adjacent
`cline-notes-ui-phase2-20261017/` directory. Captures are outside Git.

To verify: refresh Omnigent, open the Athena Cline conversation, expand
**Working notes**, and confirm the completed final reply remains visible.
The web change requires no host update. This follow-up is separate from the
permission-picker upstream PR.

