# Background hosts

Use `--background` to detach the host from its launching terminal.
The command checks that the host registers with the server before it reports success.
New Chat and host reconnection instructions include this flag.

```bash
omnigent host --server 'https://your-server.example' --background
omnigent host status --server 'https://your-server.example'
```

Sign-in runs before the command detaches.
Add `--no-open` to skip the normal web tab.
Add `--non-interactive` in a script to fail when sign-in needs user input.

## Existing foreground processes

The background command reuses a healthy host that already serves the same server.
It does not detach an existing foreground process from its terminal.
Its `already running` message therefore does not prove that closing the original terminal is safe.

Replace a foreground host with a background host when its sessions can tolerate a disconnection.
Stop the original host first, then run the background command.
Do not run `host stop` during active work without accounting for its sessions.

After an installed source or build change, a running host does not mix old preloaded code with a new runner.
The preloaded runner process checks file content and build information before each launch.
If either changed, it refuses the shared launch.
The host then starts the runner in a fresh interpreter that loads the installed version.
Existing sessions keep running.
Reconnect each idle session that must use the new version instead of restarting the shared host.

## WSL lifetime

Detaching a process does not keep its WSL distribution running.
WSL has separate idle timers for a distribution and for its virtual machine.
Microsoft documents both in [WSL configuration](https://learn.microsoft.com/en-us/windows/wsl/wsl-config#general-wsl-settings).

To disable idle shutdown, set both values in `%UserProfile%\.wslconfig` on Windows:

```ini
[general]
instanceIdleTimeout=-1

[wsl2]
vmIdleTimeout=-1
```

Apply configuration changes during a planned WSL restart.
`wsl --shutdown` stops every distribution, including active agents, sshd, and loaded SSH agents.
Start the host again from Windows PowerShell after the restart:

```powershell
wsl -d Ubuntu -u alexbeav -- /home/alexbeav/.local/bin/omnigent host --server http://172.16.1.8:8090 --background --no-open
```

The distribution name and executable path in this command belong to Alex's Eagle setup.
`--no-open` skips the browser launch that reports a `gio` error in this WSL environment.
Neither idle setting installs startup after a Windows reboot or restarts a crashed host.

## Automatic startup

A detached process needs its operating environment to remain running.
It does not install automatic startup after a reboot.
On Linux with a working systemd user manager, or on macOS with launchd, install the supported user service:

```bash
omnigent host --server 'https://your-server.example' enable --non-interactive
```

The enable command stops an existing host before it installs the service.
On Linux, use lingering when the service must run without an active login.
Check the service manager and test a real logout before relying on this behavior.

WSL installations without systemd cannot use the systemd user service.
Use the WSL lifetime settings above for terminal independence and a Windows login task for automatic startup.
The task must select the correct WSL distribution and Linux user.
Windows startup and WSL shutdown remain separate from a detached process.

### Windows sign-in

For a native Windows host, use the reviewed [silent sign-in helpers](../deploy/hosts/windows-signin/README.md).
They install the qualified fork in a separate pinned checkout and environment, then create a hidden same-user logon task without storing a task password.
The installer is a dry run unless `-Apply` is present; activation and immediate startup require `-Activate` and `-StartNow` explicitly.

Use this command to review a later upgrade to the pinned fork instead of running a stock package upgrade:

```powershell
.\install-windows-host.ps1 -Server http://172.16.1.8:8090
```

### WSL startup models

WSL with systemd can use the normal Linux user service and lingering.
WSL without systemd needs a Windows-side launcher that enters the named distribution and runs the Linux host in the foreground; do not copy the native Windows installer for that job.

A non-systemd WSL launcher must include the Linux Node directory in `PATH` and keep its foreground host attached to the waiting Windows task.
If an older host is healthy, leave it running until an idle handoff or cold start.
On a systemd WSL installation, a waiting Windows task can start the user service and hold the distribution open.
These startup models avoid changing WSL systemd settings or forcing a WSL reboot while agents are active.

## Verification

Start a background host in a terminal, then close that terminal.
Open a different terminal and run `host status` against the same server.
Check that the process and host report `online`, then send a message from the browser.
Test a logout or reboot separately if you also install automatic startup.
