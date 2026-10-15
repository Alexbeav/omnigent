# Silent Windows host startup

These helpers install the qualified Omnigent fork as a hidden Task Scheduler job for the current Windows user. The task starts at interactive sign-in without a stored task password and runs the host with `--no-open`.

The installer requires `-Server`. To preserve the existing production registration, use `http://172.16.1.8:8090`:

```powershell
.\install-windows-host.ps1 -Server http://172.16.1.8:8090
```

This is a dry run by default. Review its JSON plan, then choose the required state:

```powershell
# Install the disabled task and isolated environment.
.\install-windows-host.ps1 -Server http://172.16.1.8:8090 -Apply

# Install and activate it for the next sign-in.
.\install-windows-host.ps1 -Server http://172.16.1.8:8090 -Apply -Activate

# Also start it now. Use only when the existing native host is offline.
.\install-windows-host.ps1 -Server http://172.16.1.8:8090 -Apply -Activate -StartNow
```

The installer pins public fork `Alexbeav/omnigent` at commit `38f30aa96e9dfa01ebef8b6d09e2e19a2696fd23`. It creates a separate checkout and frozen `.venv`, then verifies `omnigent`, `omnigent-client`, and `omnigent-ui-sdk` are all `0.18.0`. It does not replace the legacy global v0.17 CLI or modify old worktrees, including dirty ones; those remain available for rollback.

The scheduled task is named `OmnigentHostV018`. It uses an interactive same-user logon trigger, `wscript.exe`, and a retrying PowerShell supervisor. No task password is stored. The launcher requests window style `0`, and observed processes had `MainWindowHandle=0`; that is limited process evidence, not a visual sign-in test. A physical sign-out/sign-in test has not been performed.

Rollback is also a dry run by default. It removes only the managed v0.18 task and restores the recorded enabled state of supported legacy native tasks:

```powershell
.\rollback-windows-host.ps1
.\rollback-windows-host.ps1 -Apply
```

If the v0.18 task is active, stopping it must be explicit:

```powershell
.\rollback-windows-host.ps1 -Apply -StopCurrentHost
```

Rollback preserves the isolated worktree, logs, global CLI, and WSL tasks. These helpers manage native Windows hosts only; they do not install or manage WSL startup.
