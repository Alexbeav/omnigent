# Native Windows terminal support

Tracking: [PLAT-89](https://youtrack.crosstalkis.com/issue/PLAT-89), a focused
follow-up to the broader Windows harness work in PLAT-52. Implementation starts
from fork source `cc854a1b6` on `feature/windows-native-support`.

## First increment: explain platform availability

The Windows host reports `unsupported-platform` for native terminal harnesses.
The server preserves that reason, blocks unsupported session creation before
persistence, and excludes these harnesses from native Smart Routing. The web
picker, composer warning, setup dialog and Harness settings explain the Windows
limitation and the Linux/macOS/WSL alternative. Installation and credential
repair are not offered for this condition. Existing SDK and ACP choices remain
independent; there is no automatic host, harness, account or billing switch.

Older hosts reporting `false` retain their existing behavior: the client cannot
infer a platform from that value. A Windows host update is required for the new
explanation. Deploy a server that understands the new readiness value before
updating hosts; older live-frame decoders reject unfamiliar readiness strings.
Linux/macOS readiness and the current Windows launch restriction remain intact.

This increment does not provide native Windows terminals. It has not been
deployed. Component, host-frame and session-create checks are distinct from
browser proof and real Windows qualification.

Development checkpoint, 2026-10-17: 575 Python checks passed, covering the
Windows gate, host frames, session creation, Smart Routing and feature maps.
The three frontend suites passed 691 tests; a subsequent focused run passed
14 cases including two additional settings/dialog cases. Two Python and four
frontend regressions fail against the original code. Ruff, Pyrefly, frontend
lint, formatting, project checks and OpenAPI freshness pass. The full
`tsc -b` check passed separately in a bounded existing-toolchain Steam Deck
lane with a 2 GiB Node heap, after the local 768 MiB limit proved insufficient.
The local hook run omits only that separately completed TypeScript check.
The exact Deck process group drained and its claim was released. Browser
proof, production rollout and native Windows execution remain pending.

## ConPTY port inputs and gaps

Audit the existing
[Windows fork at `0325b9aa3`](https://github.com/ubuntuyou/omnigent-win/tree/0325b9aa31528599cea58119379ee8555e7f4b44)
as reference material. Its LICENSE is Apache-2.0. Retain applicable attribution
and notices when adapting code; no third-party implementation has been copied
into this increment.

The fork provides one ConPTY reader with output fan-out, a serialized writer,
browser subscriptions, resizing and replay. Its README documents missing Files
and terminal-resource support, raw output instead of a rendered screen, no
keep-alive after CLI exit, and no local PowerShell terminal attach. Treat its
reported Claude/Codex success as the author's evidence, not qualification of
this fork or the installed CLI versions.

The interface audit found five public terminal methods absent from the
fork's `WindowsTerminalInstance`: `client_interaction_within`, `last_exit_signal`,
`last_exit_status`, `last_exit_text`, and `pane_pid_sync`. Current runner startup
diagnostics and terminal registry code consume those methods. Its cleanup calls
`_proc.kill_tree(pid)` with an integer, whereas our current helper requires a
process object with an owned identity. Adapting those calls is required before
reusing the implementation.

The terminal WebSocket control bridge and other consumers still invoke tmux
directly. Introduce a narrow backend interface for launch, input, resize,
screen/replay, subscribe/detach, liveness, exit diagnostics and close. Keep the
tmux implementation for POSIX. A ConPTY backend must implement that contract
rather than fabricate a socket path that tmux consumers will try to open.

[Microsoft's ConPTY guidance](https://learn.microsoft.com/en-us/windows/console/creating-a-pseudoconsole-session)
calls out independent input/output servicing and deadlock risks during close.
Test blocked reads, startup failure and cancellation as well as successful
interactive input. The terminal owner should outlive browser connections;
closing a browser is not closing the session. A host crash needs an explicit
recovery policy; ConPTY does not supply tmux's independent persistent server.
Keep bounded replay and backpressure so a slow viewer cannot grow memory
without limit. Retain process identity checks and evaluate Job Object ownership
without claiming filesystem or network isolation.

## Experimental transport increment

`omnigent.terminals.conpty` now provides a standalone transport and
`conpty_bridge` implements the existing browser binary-input/output and JSON
resize framing. Native Windows harness readiness remains disabled.

Browser attachment now has an explicit tmux or ConPTY target. The runner and
in-process server routes use one dispatcher after their existing authorization,
registry lookup and liveness checks. Tmux targets retain the existing control
bridge and popup behavior. ConPTY targets use the owned session directly and
skip tmux-only popup work; they need no fabricated socket path. The runner's
direct-attach listener shares this same handler. Both bridges retain read-only
viewing and detach without closing the terminal, and report client interactions
separately from terminal activity.

The default terminal factory remains unavailable on Windows. A process-local
`OMNIGENT_WINDOWS_NATIVE_TERMINALS=1` switch enables an experimental managed
ConPTY instance for isolated qualification. Native harness readiness remains
disabled, so the switch does not enable Claude or Codex in the host picker.
No AgentOps collector, lifecycle frame, tunnel or observation schema changes
are part of this boundary.

The transport uses pywinpty's low-level ConPTY API, with one output reader and
one serialized input worker. It bounds replay, viewer queues and pending input;
a stalled viewer gets a reconnect error instead of silently losing VT bytes.
Browser detach and adapter cancellation release only the viewer. Writable
viewers use the smallest requested dimensions; read-only viewers cannot send
input or resize. Reported partial writes stop input without retrying the payload.
Runner authentication variables are scrubbed case-insensitively, and argv is
passed literally to an executable. Batch launchers are explicitly rejected
until their native executable adapters exist.

Input futures mean the backend accepted a payload, not that the child consumed
it. The pywinpty 3.0.5 ConPTY binding buffers overlapped writes; its returned
counter can describe a previous operation, including zero for the first call.
The Windows adapter uses successful submission rather than interpreting that
counter as current-payload completion. Exceptions stop input without replay.
The binding does not expose the final buffered write's completion separately;
do not claim full-write acknowledgement from a successful future. See the
[pinned binding implementation](https://github.com/andfoy/winpty-rs/blob/v1.0.6/src/pty/base.rs).

The Windows driver requires an owned kill-on-close Job Object and retains a
process object with its birth identity for failed-setup cleanup. Assignment
happens after process creation: this does not yet prove containment of a child
that escapes during that interval. The Job Object provides no filesystem or
network isolation. A failed close reports failure and retains ownership for
retry; it does not report successful cleanup.

The optional `windows-native` extra locks pywinpty 3.0.5 under the existing
dependency cutoff. This code was written against its documented low-level API,
not copied from the reference fork. Raw VT-tail replay is bounded but is not a
rendered screen or a complete reconnect snapshot. Screen/mode reconstruction,
native harness adapters, local console attach and crash recovery still need
implementation and qualification.

Optional `capture_screen=True` maintains a bounded pyte text model alongside
the raw stream. It preserves separate normal/alternate buffers, normal history,
cursor position/visibility and bracketed-paste state, with output and capture
serialized by the same session lock. Capture is disabled by default and does
not change the browser's raw-tail replay. It is not a VT replay serializer.
Unsupported column-mode changes or oversized control strings/glyphs make capture
explicitly unavailable; raw input/output and the owned terminal stay running.
Grid/history budgets reject oversized resizes before enqueueing any OS operation.
The Windows extra now includes pyte for an explicit capture-enabled pilot.

Portable driver and browser-adapter tests cover blocked input with independent
output, atomic Unicode paste, byte bounds, partial writes, viewer overflow,
resize ownership, read-only viewing, cancellation, final output, exit status
and cleanup retry. A Windows-only process-boundary test exercises two fixture
turns, Unicode cwd and file access, reconnect, resize, exit diagnostics and
descendant cleanup. It needs a separately admitted native Windows test lane;
passing portable tests does not qualify the Windows binding or either provider.

Windows transport checkpoint, 2026-10-17: an isolated Eagle candidate passed
the real process probe with pywinpty 3.0.5. Two raw Greek/emoji input turns,
multiline content, a Greek cwd with spaces, file access, reconnect preserving
the process, resize, final output, exit status 7, descendant cleanup and both
I/O workers stopping all passed. The bounded phase peaked at approximately
103 MiB across the controller and observed descendants. All owned process
identities drained and the exact shared resource claim was released.

The first probe failed at input because the transport treated the binding's
buffered counter as current-payload completion. That failure is retained; a
portable regression fails before the fix and passes after it. The retry used
an explicitly hashed overlay in the private candidate. Production installation,
native readiness and existing sessions were unchanged. No Claude/Codex process
or provider inference was used, so this is transport qualification only.
The updated portable/readiness checks pass 48 tests, with the Windows process
test skipped on Linux and separately executed by the standalone native probe.

Run the portable checks without a provider or server:

```sh
python -m pytest tests/terminals/test_conpty.py \
  tests/terminals/test_conpty_bridge.py \
  tests/terminals/test_conpty_screen.py \
  tests/runner/test_terminal_resource_attach_ws.py \
  tests/server/routes/test_terminal_attach.py -q --reruns 0 -n 0
```

The route regressions supply a ConPTY attachment target with no tmux socket
field and exercise writable/read-only viewing. The adapter checks use an owned
in-memory driver for input, output, cancellation and slow-viewer faults. They
do not qualify the Windows binding, rendered reconnect state or either provider.

On an isolated Windows candidate with the optional extra installed, run the
same process probe directly. This avoids loading the repository's broader
pytest setup, which still has POSIX development dependencies. Choose a new,
owned directory each time:

```powershell
python -m tests.terminals.conpty_probe --root D:\work\PLAT-89-conpty-check-01
```

Add `--capture-screen` with a different owned probe directory to qualify the
text model against the real Windows binding. This is separate from raw transport
qualification and does not qualify either native provider or browser replay.

## Experimental managed terminal

The Windows factory can now create a `ConPTYTerminalInstance` in the normal
conversation registry. It supplies serialized input, rendered text capture,
threaded and asynchronous activity/idle watching, liveness, exit diagnostics
and explicit close. Browser detach leaves the owned process running. ConPTY
instances expose no tmux socket and are excluded from the tmux orphan reaper.
Failed Windows cleanup retains the registry handle and private directory for
retry, including conversation cleanup and shutdown.

The experimental factory requires an explicit `none` sandbox policy. It refuses
forked/scratch environments, copy-on-write paths, egress restrictions, inherited
active sandboxes and tmux start-on-attach rather than silently dropping those
policies. Its mandatory Job Object owns processes; it does not isolate files or
network access. Joined wrapped-line capture, complete browser replay, provider
launch adapters and crash recovery remain unfinished.

Managed-terminal checkpoint, 2026-10-18: an isolated Pegasus Windows candidate
passed 48 terminal checks (one separate process check skipped) and the standalone
managed probe with the real pywinpty binding. The probe exercised two Unicode
turns, a Greek working directory and file, rendered capture, detach/reconnect
preserving process identity, resize, exit status 7 and descendant cleanup.
The controller and observed descendants peaked at 138,027,008 bytes. All exact
owned identities drained and the resource claim was released. An initial
watcher test failed because it sent output before establishing the detector's
baseline; that failure is retained and the corrected scenario waits for the
initial idle event. No provider, existing session or host daemon changed.

To repeat the managed process boundary on an admitted private Windows candidate:

```powershell
$env:OMNIGENT_WINDOWS_NATIVE_TERMINALS = '1'
python -m tests.terminals.conpty_probe --managed --root D:\work\PLAT-89-managed-check-01
```

This proves the managed terminal boundary only. Keep the factory switch local
to the test process and leave native provider readiness disabled until the
provider-specific launch, resume, controls and recovery checks below pass.

Windows launch-request checkpoint, 2026-10-19: Codex now requests immediate
terminal startup without tmux passthrough on Windows. Claude's configured launch
uses the terminal's environment-removal controls instead of a Unix `env`
wrapper. POSIX requests retain their existing behavior. The owning portable
suites passed 450 checks, including the unchanged Windows readiness gate; both
Windows request regressions fail against the prior source. These checks do not
qualify provider executables, hooks, authentication or real Windows chats.
Native provider readiness remains disabled.

Both Windows launch requests now cap scrollback at the ConPTY screen's 10,000
line limit. The owning launch checks passed 41 cases; both Windows requests
fail screen construction against the preceding source. POSIX keeps its larger
tmux history.

An isolated Pegasus Windows runtime also started the installed Codex 0.149.1
app-server, established its Job Object and policy-hook trust, and released the
process, owner lock and Job handle. This used the existing minimal startup
profile without ambient MCPs/plugins and sent no inference request. Project
and user-hook trust were not overridden. This does not qualify real chats,
ambient tools, authentication refresh or the browser controls.

The shared Windows Job Object handle now retains ownership and raises when
`CloseHandle` fails, allowing the managed terminal's existing close retry to
work. Concurrent closes serialize and release the handle once. Two portable
fault checks and a repeated native managed probe passed; the native unit set
passed 51 checks with one skip after including the metadata and handle checks.
This is a source fix only; installed host daemons remain unchanged.

A separate app-server ownership candidate gives Windows Codex's app-server
its own mandatory Job Object, independent of the ConPTY TUI. Startup refuses
unowned processes, close retains failed ownership for retry, and hidden spawn
flags preserve the process-group flag. The real Windows Python-fixture probe
checks an absent console window and cleanup through interpreter redirectors
to the leaf process. Its readiness and hook RPCs are stubbed; it does not
qualify Codex authentication, app-server RPCs or provider inference. Joint
AgentOps lifecycle review is required before integrating this candidate.

If closing the app-server's Job handle fails, independent process termination,
owner-lock release and stderr cleanup still run; the failed handle remains
available for retry. Failed startup preserves its original readiness or
cancellation error and logs cleanup failure instead of replacing that error.

## Delivery and qualification

1. Validate and publish the platform-readiness increment separately.
2. Extract the terminal backend boundary with unchanged POSIX behavior.
3. Adapt ConPTY behind an experimental capability gate; keep unsupported
   harnesses unavailable until their Windows checks pass.
4. Qualify Claude and Codex individually on one admitted Windows host, then
   consider rollout to the remaining fleet and focused upstream PRs.

The Windows pilot must cover hidden startup, fresh and resumed two-turn chats,
Unicode/Greek paths and multiline paste, cwd/file access, model and reasoning
controls, approvals and permission modes, structured questions, MCP, images,
queue/steer/cancel, browser reload/reconnect, terminal resizing, process exit,
host recovery and owned-process cleanup. Use existing local sign-ins. Preserve
vendor trust checks and account routing; do not copy credentials between hosts
or weaken checks to make a pilot pass. Local console attach remains a separate
entry point and must be implemented or explicitly excluded from the first pilot.

For the first increment, run the owning tests:

```sh
python -m pytest tests/onboarding/test_native_harnesses_windows_unavailable.py \
  tests/host/test_frames.py tests/server/integration/test_session_create_harness_readiness.py \
  tests/server/routes/test_native_smart_routing_create.py -q --reruns 0 -n 0
cd web
node node_modules/vitest/vitest.mjs run src/lib/harnessSetup.test.ts \
  src/pages/settings/SettingsHarnessesSection.test.tsx \
  src/shell/NewChatDialog.test.tsx --maxWorkers=1 --fileParallelism=false
```

Before deploying, build the candidate and exercise the new-session picker on
desktop and mobile, the selected-harness warning, direct setup dialog, Harness
settings grid and detail page. Test both setup-feature states, native aliases,
older boolean readiness, an available SDK/ACP choice and a working Linux/WSL
native choice. Confirm an unsupported session is not created. The installed
production bundle cannot prove this undeployed candidate.

## Joined text capture increment

Managed ConPTY reads now accept `join_wrapped=True`. Joining follows observed
automatic wraps across retained screen/history rows, preserving spaces inside a
logical line. Full-width hard lines stay separate. Wrap metadata follows row
movement, stays separate in the alternate buffer and cannot retain evicted rows.
History counts still report physical rows. Raw capture and VT-tail replay remain
the defaults; native readiness and factory gates are unchanged.

Combining marks on single/double-cell bases and wide-glyph wrap padding are
handled at the drawing boundary. Zero-width format sequences (including emoji
joiners/variation selectors), glyphs wider than the grid and wide glyphs crossing
a disabled wrap boundary fail capture explicitly. Height changes and width
expansion preserve surviving wrap links. The text model clips rather than
reflows on width shrink: joined capture refuses retained rows that lost text
until they are fully erased, reset or evicted; ordinary grid capture continues.
These portable regressions do not qualify native Windows resize behavior or
either provider. Native binding/provider proof remains separate.
