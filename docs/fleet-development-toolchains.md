# Fleet development toolchains

Tracking: [PLAT-107](https://youtrack.crosstalkis.com/issue/PLAT-107).

Use an isolated source checkout and user-local environment for each validation
lane. Keep live runtimes, provider sign-ins, shared daemons and operating-system
packages separate. A copied console wrapper is insufficient: its native binary
and import dependencies must also work. Package metadata alone does not qualify
a toolchain.

## Executable preflight

Run the preflight with the interpreter that will run the checks. It installs
nothing, changes no configuration, starts no provider and prints no credentials
or failed-command output. Each executable probe has a five-second timeout.
An exit code of zero means this profile's probes passed; it does not grant a
resource claim or qualify a product build or provider.

```sh
.venv/bin/python scripts/check_development_toolchain.py --profile portable-checks
```

The portable profile uses Python 3.12 and Node 24.x, the versions used by the
current isolated validation lane. Ruff, Pyrefly, pytest and pre-commit must match
the checkout's `uv.lock`, and their executable probes must succeed. Imports of
the two editable SDKs and Omnigent must resolve to this checkout. TypeScript
must resolve from `web/package.json`, including when backend project lints run.
A committed Git baseline containing `uv.lock` is required so file-hygiene hooks
can distinguish an existing large file from a newly added file.

For a separately admitted Windows transport candidate:

```powershell
.venv\Scripts\python.exe scripts\check_development_toolchain.py --profile windows-conpty
```

This profile verifies Windows/Python 3.12, the source SDKs, Git baseline and
locked pywinpty/pyte packages, including actual imports of the extension. It
does not launch a terminal or either provider. Repository hooks still assume
POSIX executable paths and Bash; passing this native profile does not establish
a complete native Windows development environment.

## Bootstrap and fleet qualification gates

The initial preflight is diagnostic. The repaired private Deck lane still
borrows existing read-only Python and frontend dependencies. Fleet-wide
standardization remains open until a clean, repeatable bootstrap exists for
each admitted OS and architecture.

The bootstrap must use the source lockfiles, include actual native executables,
resolve source SDKs and frontend dependencies, and preserve the operating
system's Python, SteamOS read-only packages and existing services. Keep host
access, trust and authentication checks intact. Git identity and credential
availability need a separate check that never prints identity or token data;
this preflight does not test publishing credentials.

Record the profile, source commit, lockfile hashes, actual runtime versions,
preflight JSON and bounded validation outcome per host. Confirm fresh foreground,
memory and shared claims before tests; record owned process identity and drain
before releasing a claim. Do not borrow an old claim or stop unrelated sessions
to obtain capacity. Toolchain receipts are validation artifacts, independent of
the passive AgentOps telemetry collectors.
