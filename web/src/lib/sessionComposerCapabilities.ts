import type { ServerInfo } from "@/lib/capabilities";
import { isCostRoutingSession } from "@/components/CostRoutingControl";
import {
  SMART_ROUTING_ARMS,
  hostBacksHarnessWithGateway,
  smartRoutingSourceFor,
} from "@/lib/smartRoutingAvailability";
import {
  isNativeTerminalSession,
  nativeCodingAgentForSession,
  nativeCodingAgentForHarness,
} from "@/lib/nativeCodingAgents";
import type { NativeModelOption, Session } from "@/lib/types";

import { codexEffortLevelsForModel } from "@/lib/codexNativeModels";
import { supportsEffortControl } from "@/lib/sessionCapabilities";
import { isClaudeNativeSession } from "@/lib/claudePermissionMode";
import { isCodexNativeSession } from "@/lib/codexPlanMode";

const EFFORT_LEVELS = ["low", "medium", "high"] as const;

/** Anthropic-side efforts for claude-native sessions (matches ANTHROPIC_EFFORTS in reasoning_effort.py). */
const CLAUDE_NATIVE_EFFORT_LEVELS = ["low", "medium", "high", "xhigh", "max"] as const;

/** Pi thinking ladder (matches PI_EFFORTS in reasoning_effort.py; ``ultra`` aliases to ``max`` on Pi so omitted). */
const PI_NATIVE_EFFORT_LEVELS = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

export type NativeModelPickerKind =
  "claude" | "codex" | "cursor" | "kiro" | "opencode" | "pi" | "devin" | "acp" | "configured";

/**
 * A custom (label-less) session resolved to the native Codex harness.
 *
 * Custom YAML agents get no `omnigent.wrapper` presentation label, so the
 * resolved harness is the capability evidence. Any wrapper label — including
 * sub-agent variants like `codex-native-ui-subagent`, which cannot honor
 * mid-session overrides — keeps the label authoritative and skips the
 * fallback.
 */
/**
 * The wrapper label a session behaves as: its own, else the one its harness
 * implies.
 *
 * A session created before its harness was renamed carries no
 * ``omnigent.wrapper`` label — the ACP-era Devin rows are the live example — so
 * every label-driven surface below (model picker, effort ladder, permission mode)
 * would read it as non-native even though the runner resolves it to a native
 * harness and gives it a pane. Deriving from the harness fixes that for any
 * rename, and subsumes the codex-only special case this replaces.
 *
 * A sub-agent child is excluded: it owns no PTY and takes no input, so it must
 * not gain a picker just because its harness is native.
 */
function effectiveWrapperLabel(
  conv:
    | {
        labels?: Record<string, string | null> | null;
        harness?: string | null;
        parentSessionId?: string | null;
      }
    | null
    | undefined,
): string | undefined {
  const label = conv?.labels?.["omnigent.wrapper"];
  if (label != null) return label;
  if (conv?.parentSessionId != null) return undefined;
  return nativeCodingAgentForHarness(conv?.harness)?.wrapperLabel;
}

export function effortLevelsForConv(
  conv:
    | {
        labels?: Record<string, string | null> | null;
        harness?: string | null;
        parentSessionId?: string | null;
      }
    | null
    | undefined,
  codexModelOptions: readonly NativeModelOption[] = [],
  currentModel: string | null = null,
): readonly string[] {
  switch (effectiveWrapperLabel(conv)) {
    case "claude-code-native-ui":
      return CLAUDE_NATIVE_EFFORT_LEVELS;
    case "devin-native-ui":
      // Devin encodes effort as a model-variant suffix, and the rung set is
      // PER MODEL (swe-2 exposes only medium/high/max; `swe-2-low` is a different
      // Fusion model), so derive it from the selected model's catalog entry —
      // its `supportedReasoningEfforts` — rather than a fixed ladder.
      return codexEffortLevelsForModel(codexModelOptions, currentModel);
    case "codex-native-ui":
      return codexEffortLevelsForModel(codexModelOptions, currentModel);
    case "pi-native-ui":
      return PI_NATIVE_EFFORT_LEVELS;
    default:
      return EFFORT_LEVELS;
  }
}

/**
 * Which native model picker should be visible for *conv*?
 *
 * Gated on the wrapper label, not `omnigent.ui === "terminal"`:
 * other terminal-first wrappers may not be Claude/Codex-native (see
 * `TerminalFirstContext.tsx`).
 */
export function modelPickerKindForConv(
  conv:
    | {
        labels?: Record<string, string | null> | null;
        harness?: string | null;
        parentSessionId?: string | null;
        inferenceConfigured?: boolean;
      }
    | null
    | undefined,
  modelOptions: readonly NativeModelOption[] = [],
): NativeModelPickerKind | null {
  switch (effectiveWrapperLabel(conv)) {
    case "claude-code-native-ui":
      return "claude";
    case "codex-native-ui":
      return "codex";
    case "cursor-native-ui":
      return "cursor";
    case "kiro-native-ui":
      // Launch-only model selection: kiro applies ``--model`` at launch. Unlike
      // cursor/opencode there is no terminal->web model mirror, so the picker
      // reflects the pre-launch ``model_override`` selection.
      return "kiro";
    case "opencode-native-ui":
      // Like cursor: a vendor-owns-model wrapper that mirrors its live TUI
      // model into the session ``model_override`` (the forwarder's terminal→web
      // mirror), so the picker surfaces that as the live model.
      return "opencode";
    case "devin-native-ui":
      // Like opencode/pi: Devin mirrors its live model into ``model_override``
      // (the executor types ``/model`` when a routed model changes).
      return "devin";
    case "pi-native-ui":
      // Like cursor: the runner types a model switch into the live Pi process
      // (via the bridge inbox → Pi's ``setModel``) and Pi mirrors its own
      // ``/model`` picks back to ``model_override`` via the extension's
      // model_select handler, so the picker surfaces that as the live model.
      return "pi";
    default:
      if (conv?.inferenceConfigured) return "configured";
      // Generic ACP sessions carry no wrapper label; the server canonicalizes
      // ``acp:<slug>`` ids to "acp" in the snapshot's harness field.
      if (conv?.harness === "acp" && modelOptions.length > 1) return "acp";
      return null;
  }
}

export function shouldShowModelPicker(
  conv:
    | {
        labels?: Record<string, string | null> | null;
        harness?: string | null;
        inferenceConfigured?: boolean;
      }
    | null
    | undefined,
  modelOptions: readonly NativeModelOption[] = [],
): boolean {
  return modelPickerKindForConv(conv, modelOptions) !== null;
}

/**
 * True when effort controls should be visible.
 *
 * :param conv: Session or sidebar row carrying labels. ``null`` or missing
 *     labels fail closed.
 * :returns: True only when the session supports Web UI effort controls.
 */
export function shouldShowEffortPicker(
  conv:
    { labels?: Record<string, string | null> | null; harness?: string | null } | null | undefined,
): boolean {
  return supportsEffortControl(conv);
}

export function shouldShowCodexPlanModeControl(
  conv: { labels?: Record<string, string | null> | null } | null | undefined,
): boolean {
  return isCodexNativeSession(conv);
}

/**
 * True when the claude-native permission-mode picker should be visible.
 *
 * Claude-native sessions only: the switch drives Claude Code's own
 * shift+tab cycle, which no other harness has.
 *
 * :param conv: Session-like object carrying `labels`; a missing session
 *     or missing labels fails closed.
 * :returns: True only for sessions running the claude-native wrapper.
 */
export function shouldShowPermissionModeControl(
  conv: { labels?: Record<string, string | null> | null } | null | undefined,
): boolean {
  // Devin cycles its own rungs with Shift+Tab, which the runner drives, so it
  // gets the same control — with its own vocabulary (see `permissionOptions`).
  return isClaudeNativeSession(conv) || modelPickerKindForConv(conv) === "devin";
}

/**
 * True when the codex-native approval-mode picker should be visible.
 *
 * Codex-native sessions only: the switch drives Codex's own approval/sandbox
 * presets (the ``/permissions`` popup), which no other harness has.
 *
 * :param conv: Session-like object carrying `labels`; a missing session or
 *     missing labels fails closed.
 * :returns: True only for sessions running the codex-native wrapper.
 */
export function shouldShowCodexApprovalModeControl(
  conv: { labels?: Record<string, string | null> | null } | null | undefined,
): boolean {
  return isCodexNativeSession(conv);
}

/**
 * True when the session Goal control should be visible.
 *
 * @param conv - Session or sidebar row carrying labels. ``null`` or missing
 *   labels fail closed.
 * @returns True only for Codex-native wrapper sessions until the server
 *   advertises a generic goal capability.
 */
export function shouldShowGoalControl(
  conv: { labels?: Record<string, string | null> | null } | null | undefined,
): boolean {
  return isCodexNativeSession(conv);
}

/** True for top-level Polly sessions running on the Claude SDK harness. */
export function shouldShowPollyClaudeGoalControl(
  session: Pick<Session, "agentName" | "harness" | "parentSessionId"> | null | undefined,
): boolean {
  return (
    session?.parentSessionId == null &&
    session?.agentName?.toLowerCase() === "polly" &&
    session?.harness === "claude-sdk"
  );
}

/** True for top-level Polly sessions running on the Codex harness. */
export function shouldShowPollyCodexGoalControl(
  session: Pick<Session, "agentName" | "harness" | "parentSessionId"> | null | undefined,
): boolean {
  return (
    session?.parentSessionId == null &&
    session?.agentName?.toLowerCase() === "polly" &&
    session?.harness === "codex"
  );
}

/**
 * Whether the session's own model can be routed per turn.
 *
 * SDK/bundle agent sessions need only the deployment flag. Native Claude
 * Code / Codex panes ARE routable per turn — the server injects the routed
 * pick via ``/model`` when ``cost_control_mode_override`` is on, the same
 * apparatus the create-time gear arms — but only when a router can answer
 * for their family (the server rejects a routing-on create otherwise): the
 * external AI-Gateway router needs the family's inference gateway-backed on
 * the session's host, and the built-in judge covers the rest. An absent
 * host row reads as backed, mirroring {@link hostBacksHarnessWithGateway}.
 */
export function isCostRoutingEligible(
  serverInfo: ServerInfo | "loading",
  // Only the fields the guards below read, so a temp/optimistic session can be
  // evaluated from its seed without fabricating a whole Session. A real Session
  // is structurally assignable.
  session: Pick<Session, "agentName" | "parentSessionId" | "harness" | "labels"> | null | undefined,
  host?: { gateway_inference?: Record<string, boolean> | null } | null,
): boolean {
  if (serverInfo === "loading" || !serverInfo.smart_routing_enabled) return false;
  if (!isCostRoutingSession(session)) return false;
  if (!isNativeTerminalSession(session)) return true;
  const native = nativeCodingAgentForSession(session);
  if (native === undefined || !SMART_ROUTING_ARMS.some((arm) => arm === native.harness)) {
    return false;
  }
  return (
    smartRoutingSourceFor({
      externalConfigured: serverInfo.smart_routing_sources.external,
      ossConfigured: serverInfo.smart_routing_sources.oss,
      gatewayBacked: hostBacksHarnessWithGateway(host, native.harness),
    }) !== null
  );
}
