# Passive native session metadata

The server accepts version 1 passive snapshots through the existing authenticated
host tunnel. It stores them separately from conversations. This change does not
install a reader, create a chat, import a transcript or control a native session.
Readers must be qualified and enabled separately after the server supports the frame.

## Wire contract

`HostNativeObservationsFrame` carries `host.native_observations` with a `snapshot`
object. The authenticated tunnel supplies the host and owner identity. A snapshot
cannot select a different host or account. The contract lives in
`omnigent/native_observations.py`.

Each snapshot names one of `claude`, `codex` or `cline`. It contains a producer
epoch, an increasing sequence, scan time, coverage status, capability names and
at most 2,000 native observations. Its serialized metadata is limited to 1 MiB.
Unknown fields, raw paths, prompts, commands and message bodies are rejected.
Native identifiers use a bounded character set and never depend on a process ID.

Each observation keeps its native ID, optional parent ID, surface, launch origin,
state, event, evidence time and presence flag. Launch origin defaults to unknown.
An adapter must not claim managed ownership merely because a process exists.
The server does not perform fuzzy identity matching or automatic conversation binding.

`context_tokens` means verified current context usage, not cumulative billed usage.
It and `context_window` remain null if the reader has no qualified usage signal.
Lifecycle, human-wait and usage values require corresponding source capabilities.

## Persistence and replay

The `native_observation_sources` table stores one compressed snapshot per
workspace, host and harness. A normal schema migration creates this table.
No production schema change occurs merely by preparing this code.

Duplicate or decreasing sequences in the same producer epoch are ignored.
An older scan cannot replace a newer scan except for qualified clock repair
described below. A row with older evidence cannot replace a newer qualified fact.
An incomplete source retains previously observed rows.
Stored facts retain their original state when current capabilities shrink;
the read projection cannot count them as active without current lifecycle support.
Only a complete current inventory can establish absence. A merged inventory
that exceeds the bound is rejected instead of silently dropping observations.

The current host tunnel generation must still own the connection when a frame
is received. Persistence checks host ownership and account generation again.
The read path excludes snapshots from a different owner, workspace or account
generation. An invalid stored payload reports an unavailable source.

## Read API

`GET /v1/observations?limit=100&after=<cursor>` returns owner-scoped managed and
passive native metadata. The endpoint is mounted only
when host support is configured. Local single-user mode uses its existing local
identity. This endpoint provides no HTTP write, launch, import or control action.
An unattended reader uses an explicitly approved read-only delegated identity.

The existing device-authorization flow recognizes client ID
`omnigent-observations-read-only`. Its consent page states the narrow purpose.
It issues `observations:read` tokens, which allow only GET/HEAD on `/health` and
`/v1/observations` and `/v1/resources`. They cannot read conversations, launch hosts, approve prompts
or use administrative endpoints. Existing account, expiry and revocation checks
still apply. Refresh keeps this exact scope even if a client requests wider access.
The ordinary first-party login and other delegated clients keep their existing
authority. No extra token store or confidential machine account is introduced.

Production device authorization remains opt-in. Deployment must qualify the
existing consent/client-secret configuration, record owner consent and keep the
rotating refresh credential in the configured secret store. This code does not
enable the device flow or mint a production credential.

The response has `version`, `snapshot_id`, `as_of`, `data`, `sources`, `has_more`
and `next_cursor`. The revision hashes the complete owner-scoped reconciliation
and source versions before paging. Consumers require the same revision and
source inventory across every page; a change fails that poll rather than mixing
inventories. Original observation timestamps are not changed by this revision.
Each source includes its producer epoch and sequence for reconciliation receipts.
`managed_complete` confirms that the managed inventory was configured and read.
The existing session store's owner filter includes parents, children and archives;
shared-only sessions are excluded. A failed or oversized managed scan fails the
request instead of presenting a partial inventory as complete. The current bound
is 10,000 managed sessions, paged in batches of 1,000.

Reconciliation uses the exact owned host, resolved native harness and validated
native ID. It never inherits a child's host from its parent or identifies Cline
from generic ACP readiness. A verified native/managed pair appears in one row
with both provenance values and a metadata-only `managed` list. Multiple managed
bindings for one composite key produce one `AMBIGUOUS` row with UNKNOWN effective
state; no binding wins silently. Incomplete identities stay `UNRESOLVED`.
Managed rows without native evidence keep the reported state separate and report
UNKNOWN effective state: the existing managed state has no transition timestamp.
Neither conversation update time nor runner heartbeat supplies that missing time.
Titles, labels, paths, agent instructions and message content are not exported.
Rows are ordered by host, harness and native ID. Follow `next_cursor` until
`has_more` is false. The limit range is 1 through 1,000. Pagination follows live
keys; it is not a frozen multi-request snapshot. Consumers reject a changed
revision and reconcile removals only after a complete consistent inventory.
Record the source versions/times used for a parity receipt.

Every owned host has one coverage entry for each required harness. An old host
with no snapshot reports `NOT_REPORTED`. A host's launch readiness does not
establish passive observation support. Missing capability data means unknown.

`received_at` is server receipt time. `scanned_at` is host scan time.
`observed_at` is native evidence time and never advances because of a read,
heartbeat or replay. A source expires 120 seconds after its latest accepted
snapshot. Offline hosts report unavailable. Clock differences above five seconds
report `CLOCK_SKEW`. Operators must resolve the clocks instead of redating evidence.

A higher sequence can repair an earlier future-clock scan when the old scan was
more than five seconds ahead of its server receipt and the new scan agrees with
the server clock within five seconds. Replayed sequences and ordinary rollback
remain rejected. Previously stored future activity, removal and usage facts are
quarantined as Unknown or null before merging. Native file cursors apply the same
rule when the host clock moves back, including unchanged files. New native events
keep their own timestamps; no fact is retimed to the scan or receipt.

The cached native reader retains one pending disk scan across reconnects.
Initial cursor reads run inside that same worker, rather than on the event loop.
Connection cancellation does not wait for that scan or start another cursor
writer. A blocked filesystem read leaves observations stale until it returns.
Optional metadata persistence runs outside the tunnel receive loop. Each
connection coalesces at most four queued sources (three harnesses and resources),
plus one source being processed. One router-wide disk worker is retained across
reconnects so blocked writes cannot accumulate threads. A stalled writer delays
optional telemetry for the replica; control replies and keepalives continue.
Disconnect cancels the connection worker and drops its backlog without waiting
for disk I/O. Queued and transaction-start writes check the current connection;
existing workspace, owner, account-generation and replay fences still apply.

`effective_state` becomes `UNKNOWN` when the source or native evidence is stale,
unavailable or from the future. Original state and timestamps remain visible until
invalid future facts are quarantined during a subsequent merge or cursor read.
The presence flag is separate from state. A removed row cannot count as an active
agent. Host availability and a complete inventory do not prove that idle resources
are free or that a native session is currently executing.

## Deployment boundary

This is an additive server/transport change. Existing hosts send no new frames
and continue to work. Standalone Codex, Claude Code and Cline readers, service
identity qualification, fleet rollout and Grafana integration are separate steps.
Do not restart a shared host daemon or a production server to test this increment.
