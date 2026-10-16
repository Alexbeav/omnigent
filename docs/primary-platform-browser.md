# Firefox from Omnigent web

The Eagle setup connects web chats to the existing Windows Firefox profile through FoxPilot MCP.
MCP is the tool protocol between the coding agent and the browser bridge.
Firefox keeps its tabs, cookies, extensions and logins in its normal profile.
The Omnigent desktop app is not required.
The web UI does not embed Firefox or stream its window.

## Connection

The connection is Omnigent web, the selected agent on Eagle WSL, a local MCP process, and the Firefox add-on.
The MCP process uses native Windows Node so the bridge and Firefox share Windows loopback.
The broker listens on `127.0.0.1:8089` and `[::1]:8089`.
No public listener, LAN firewall rule, remote relay, or browser debugging flag is configured.
Eagle, its WSL host and Firefox must remain running when controlling it from a phone.

The installed package is `foxpilot-mcp@1.0.29`.
Its npm artifact passed SHA-512 integrity verification before installation.
The signed Firefox Add-ons package is version `1.0.22`, with a compatible protocol version.
Both are third-party FoxPilot components, not Mozilla's own MCP server.

Eagle WSL has a `foxpilot` MCP entry in these user configurations:

- `~/.codex/config.toml` for native Codex chats.
- `~/.claude.json` for Claude Code chats.
- `~/.cline/data/settings/cline_mcp_settings.json` for Cline.

Each entry launches the same server:

```json
{
  "command": "/mnt/c/Program Files/nodejs/node.exe",
  "args": [
    "C:\\Users\\Alexbeav\\.local\\share\\omnigent-browser\\foxpilot-1.0.29\\dist\\server.js"
  ],
  "env": {
    "EXTENSION_PORT": "8089"
  }
}
```

These paths apply to agents running on Eagle WSL.
Other hosts need their own connection configuration.
The original configurations are in private backups under `~/.local/state/omnigent-browser/backups/20261016/`.
No browser cookies or provider authentication values were copied into this setup.

## Use and verification

Install [FoxPilot from Firefox Add-ons](https://addons.mozilla.org/en-US/firefox/addon/foxpilot/) in the usual Firefox profile.
Keep that Firefox window open.
Start a fresh Codex, Claude Code or Cline chat on Eagle WSL so it loads the new MCP configuration.
Open FoxPilot's options and select Automation Mode.
Turn on Enable Automation Mode and accept Firefox's permission to access all websites once.
This saved grant removes the per-domain permission requests and enables clicks, typing, snapshots and screenshots.
Turning Automation Mode off removes the all-websites grant again.
Ask the chat to use FoxPilot to open `https://example.com` and read its text.
If Automation Mode stays off, reading each new domain requires its own browser permission.

FoxPilot tools include `list-browsers`, `open-browser-tab`, `get-tab-web-content`, `take-snapshot`, `click-element` and `fill-element`.
The Omnigent `browser_*` tools still target the desktop app's embedded browser.
Ask for FoxPilot when both sets appear.
Give concurrent agents separate tabs so they do not edit the same page at once.

Direct MCP initialization, discovery of 45 tools and connection to the existing Firefox profile pass.
The native Codex source reader discovers the new configuration, and Claude resolves the updated global configuration.
Reading the Example Domain page passes after domain consent.
A fresh native Codex chat calls `mcp__foxpilot__list_browsers` and receives an active Firefox result.
Its native transcript confirms the actual tool call.
Alex enabled Automation Mode and accepted the one-time all-websites permission.
This existing native Codex chat then opened `https://example.org/` without another domain-permission error.
Snapshots, filling a temporary field, clicking its local button and reading the confirmation all pass.
The same check returned a PNG screenshot and closed its owned test tab.
No external form was submitted.
Claude/Cline browser turns and profile persistence across a browser restart remain unproven.
Private checks and source pins are under `.omnigent/verify/browser-integration-20261016/`.
The homelab Infrastructure-State note owns current installation and validation status.

## Removal

Remove only the `foxpilot` entry from each provider configuration.
Preserve other MCP servers and subsequent configuration edits.
Restart or reload affected agent sessions, then disable or remove the Firefox add-on.
The broker exits when no clients or extensions remain connected.
The private backup copies remain available if a configuration needs repair.

## References

- [FoxPilot source and setup](https://github.com/balakumardev/foxpilot).
- [Signed Firefox add-on](https://addons.mozilla.org/en-US/firefox/addon/foxpilot/).
- [Mozilla's alternative Firefox MCP server](https://github.com/mozilla/firefox-devtools-mcp), including its existing-browser connection mode.
