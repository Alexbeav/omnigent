# Host resource sampling candidate

PLAT-101 covers this isolated read-only implementation. The combined candidate
includes an opt-in publisher, authenticated host frame, persistent store and
read API. It is not enabled in running daemons or deployed to the production
server. Existing sessions remain unchanged. Windows launch and terminal work
remains with PLAT-89.

`omnigent.host.resource_observations.sample_host_resources()` measures a 250 ms CPU interval through the existing psutil dependency. It reads physical memory total and OS-available memory. Used percent is `100 * (total - available) / total`. This definition is explicit because native operating-system displays can classify cache or reclaimable memory differently.

The CPU measurement blocks only its worker thread, not the event loop. The
candidate publisher samples every 30 seconds and retains one pending worker
across tunnel reconnects. Cancellation does not start another concurrent sensor
read. A three-second sampling deadline and five-second send deadline contain
failures; a hung OS call retains that single worker until it returns. No worker
controls a session. Sustained cost and independent measurement tolerances still
need fleet qualification.

CPU/RAM fields have separate source times. Failed or invalid readings remain null with no source time. Missing data never becomes zero. GPU failure does not discard valid CPU/RAM readings.

The optional NVIDIA query requests only bounded index, utilization and memory counters. It has a two-second timeout and fixed arguments. No GPU UUID, model name, process list, command, path, prompt, transcript, provider secret or raw error enters the result. NVIDIA memory fields use MiB converted to bytes.

On Linux, the optional AMD adapter reads `gpu_busy_percent` for AMD sysfs devices. GPU memory remains null until its meaning is qualified, especially on shared-memory systems. macOS GPU counters are Unsupported by this candidate. This does not claim that macOS itself has no GPU telemetry. Missing NVIDIA/AMD sensors elsewhere remain Unknown.

## Authenticated transport and read path

`HostResourceObservationsFrame` carries `host.resource_observations` and a
`HostResourceSnapshot`. The tunnel supplies host/owner identity. The 16 KiB
contract rejects extra fields, inconsistent memory counters, invalid percentages,
unqualified GPU completeness and missing source times. It allows at most 32 GPU
devices. A producer epoch and increasing sequence fence replay; older scans cannot
replace newer data. Receipt time does not advance on replay or read.

`host_resource_sources` stores one compressed sample per workspace/host. Reads
and writes check host ownership and account generation. The additive migration
follows the passive-session migration and is reversible. No production migration
has been run by preparing this source.

`GET /v1/resources` returns only the caller's owned hosts. Missing sources are
`NOT_REPORTED`; offline/corrupt, stale and clock-skewed sources are explicit.
Samples expire after 90 seconds. Original per-sensor times remain available.
The existing `observations:read` device grant allows GET/HEAD to this path plus
health and session observations; mutation, session control and admin access
remain denied. Consent text includes CPU, memory and GPU measurements.

The existing daemon calls the publisher only when
`OMNIGENT_RESOURCE_OBSERVATIONS=1`. Default is disabled. Server support must land
first; joint review and owner-approved idle handoffs precede enabling this flag.
No new fleet service, provider configuration or native hook is installed.

The AgentOps consumer requires explicit authenticated-host-to-physical-host
bindings. A WSL sample cannot populate physical CPU/RAM, even if it belongs to
the same PC. Unknown or ambiguous mappings remain unbound. The authenticated
AgentOps `/metrics` projection omits unavailable numeric values and provides
separate validity gauges. Hardware samples do not enter Loki. Prometheus scrape
deployment, Grafana hardware queries and sustained fleet qualification remain
separate from this isolated source increment.

Optional persistence shares the bounded worker described in
[native session observations](native-session-observations.md). Slow resource
writes cannot hold the tunnel receive loop, and reconnects reuse the existing
disk slot. A blocked writer can make optional telemetry stale across the replica.
Connection backlogs are coalesced and discarded on disconnect; a late write
checks the registered connection inside its transaction before accepting data.
