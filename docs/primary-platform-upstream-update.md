# Upstream update and contribution plan

Status: proposed plan, researched on 2026-10-16.
This note specifies future work. It does not record an implemented upgrade.
The deployed application remains `2050948e3` from [the primary platform work](primary-platform-plan.md).

## Recommended targets

Use release `v0.18.0` plus our required enhancements as the default deployment target.
Backport the upstream Claude request-record fix before testing this candidate.
Prepare contribution branches against current upstream `main` separately.
This separates production qualification from the contribution baseline.
The deployment preference question remains open; this plan covers either answer.

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
No candidate build, restored-database test, mixed-version test or provider turn ran for this investigation.

## Enhancement disposition and PR sequence

Upstream PRs target current `main`, use one issue per behavioral PR and follow the repository template.
The desktop pane proposal needs an issue and maintainer design discussion before a large PR.
No upstream issue, comment or PR was published during this investigation.

| Group | Deployment treatment | Upstream treatment |
| --- | --- | --- |
| Image MIME fallback | Port the filename fallback for empty/generic MIME while retaining rejection of explicit conflicting types. | First small independent PR, with current attachment-suite proof. No exact title match surfaced in the searches; recheck before publishing. |
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
| `9e7908fb3`, `da86edcfc` | Generated ACP spawn grant and delegation guidance. | Port remaining behavior after inspecting current bundle composition. |
| `304bbdf8a` | ACP permission-mode precedence and policy behavior. | Existing Alex PR [#7375](https://github.com/omnigent-ai/omnigent/pull/7375) remains open; upstream also contains `ccaa42e92`. Compare the code and tests, then retain only the residual difference. |
| `92f35bbf2` | UTF-8 host/config reads on Windows. | Compare upstream legacy-encoding fixes, then port only unmet cases. |
| `93eff9b2f` | Approval-mode header badge. | Preserve the visible behavior while integrating current header controls. |
| `e20cbf347` | Docker build-context exclusions. | Compare upstream Dockerfile-specific ignore rules. Keep classic-builder support only if still required and tested with the actual build inputs. |
| `a6544e17e` | Windows detached daemon survival after terminal closure. | Preserve behavior and verify it on Windows; a POSIX test does not establish Windows console survival. |
| `8a6e5c511`, `e88754218` | ACP stalled-turn diagnostics, cancellation and wedged-session recovery. | Port tests first against the changed executor; retain only missing behavior. |
| `3c4b9c031`, `fb9a4172d`, `495202339` | Same-owner peer delivery, bounded attribution, title safety and exchange proof. | Retain in the deployment fork while coordinating the upstream API separately. |
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
