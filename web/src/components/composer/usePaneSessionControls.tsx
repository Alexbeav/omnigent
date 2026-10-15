import { useServerInfo } from "@/lib/CapabilitiesContext";
import {
  isCostRoutingEligible,
  effortLevelsForConv,
  modelPickerKindForConv,
  shouldShowCodexApprovalModeControl,
  shouldShowCodexPlanModeControl,
  shouldShowEffortPicker,
  shouldShowModelPicker,
  shouldShowPermissionModeControl,
} from "@/lib/sessionComposerCapabilities";
import { useRef, useState } from "react";
import { toast } from "sonner";
import { HostBadge } from "@/components/HostBadge";
import { useConversationEntryState } from "@/hooks/useConversationEntryState";
import { useSession } from "@/hooks/useSession";
import { useHostModelOptions, useHosts } from "@/hooks/useHosts";
import { livenessRowFromSession, useSessionLiveness } from "@/hooks/useSessionLiveness";
import { BRAIN_HARNESS_LABELS } from "@/lib/agentLabels";
import {
  CLAUDE_NATIVE_SWITCHABLE_PERMISSION_MODES,
  claudePermissionModeLabel,
} from "@/lib/claudePermissionMode";
import {
  CODEX_NATIVE_RUNTIME_APPROVAL_PRESETS,
  codexApprovalModeLabel,
} from "@/lib/codexApprovalMode";
import { DEVIN_NATIVE_PERMISSION_MODES } from "@/lib/nativeHarnessModes";
import { nativeCodingAgentForHarness } from "@/lib/nativeCodingAgents";

import { useChatStore } from "@/store/chatStore";
import { ComposerPermissionPicker } from "./ComposerControls";
import { SessionHarnessPicker } from "./SessionHarnessPicker";

/** The main composer's controls, bound to an ordinary split-pane session. */
export function usePaneSessionControls(sessionId: string | null) {
  const { session } = useSession(sessionId);
  const state = useConversationEntryState(sessionId);
  const serverInfo = useServerInfo();
  const { data: hosts } = useHosts({
    includeSandbox: true,
    enabled: sessionId !== null && !!session?.hostId,
  });
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const kind = modelPickerKindForConv(session, state.codexModelOptions);
  const probeHarness =
    kind === "codex" || kind === "claude" || kind === "devin" ? `${kind}-native` : "";
  const { data: hostModels } = useHostModelOptions(
    sessionId ? (session?.hostId ?? null) : null,
    probeHarness,
    probeHarness !== "" && !session?.inferenceConfigured && state.codexModelOptions.length === 0,
  );
  const models =
    !session?.inferenceConfigured && state.codexModelOptions.length === 0
      ? (hostModels ?? state.codexModelOptions)
      : state.codexModelOptions;
  const efforts = effortLevelsForConv(
    session,
    models,
    state.llmModel ?? state.sessionModelOverride,
  );
  const liveness = useSessionLiveness(sessionId ?? undefined, livenessRowFromSession(session));
  const unreachable = liveness.kind === "host_offline" || liveness.kind === "local_stranded";
  const showClaudePermissions = shouldShowPermissionModeControl(session);
  const showCodexPermissions = shouldShowCodexApprovalModeControl(session);
  const devin = kind === "devin";
  const permission = showClaudePermissions ? state.claudePermissionMode : state.codexApprovalMode;
  const permissionOptions = showClaudePermissions
    ? devin
      ? DEVIN_NATIVE_PERMISSION_MODES
      : CLAUDE_NATIVE_SWITCHABLE_PERMISSION_MODES
    : CODEX_NATIVE_RUNTIME_APPROVAL_PRESETS;
  const permissionLabel = showClaudePermissions
    ? devin
      ? (permissionOptions.find((row) => row.value === permission)?.label ?? permission)
      : claudePermissionModeLabel(permission)
    : codexApprovalModeLabel(permission);
  const apply = async (change: (id: string) => Promise<void>) => {
    if (!sessionId || unreachable || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      await change(sessionId);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to update chat configuration");
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const nativeAgent = nativeCodingAgentForHarness(state.sessionHarness);
  return {
    unreachable,
    leading:
      sessionId && session ? (
        <>
          <HostBadge sessionId={sessionId} appearance="composer" />
          {(showClaudePermissions || showCodexPermissions) && (
            <ComposerPermissionPicker
              label="Permission mode"
              value={permissionLabel || "Permission mode"}
              harness={state.sessionHarness}
              selectedValue={permission}
              options={permissionOptions}
              disabled={unreachable || busy}
              onSelect={(mode) =>
                void apply((id) =>
                  showClaudePermissions
                    ? useChatStore.getState().setClaudePermissionMode(mode, id)
                    : useChatStore.getState().setCodexApprovalMode(mode, id),
                )
              }
            />
          )}
        </>
      ) : null,
    trailing:
      sessionId && session ? (
        <SessionHarnessPicker
          busy={busy}
          busyRef={busyRef}
          setBusy={setBusy}
          agentName={session.agentName ?? null}
          harnessLabel={
            nativeAgent?.displayName ??
            BRAIN_HARNESS_LABELS[state.sessionHarness ?? ""] ??
            state.sessionHarness
          }
          showModels={shouldShowModelPicker(session, models)}
          showEffort={shouldShowEffortPicker(session) && efforts.length > 0}
          effortLevels={efforts}
          modelPickerKind={kind}
          supportsModelReset={
            !!session.inferenceConfigured ||
            (kind !== null && ["opencode", "acp", "configured"].includes(kind))
          }
          codexModelOptions={models}
          inferenceConfigured={session.inferenceConfigured}
          inferenceError={session.inferenceError}
          modelLabelOptions={state.codexModelOptions}
          modelLabelHostId={session.hostId}
          costRoutingEligible={isCostRoutingEligible(
            serverInfo,
            session,
            hosts?.find((host) => host.host_id === session?.hostId),
          )}
          disabled={unreachable}
        />
      ) : null,
    showPlan: sessionId !== null && shouldShowCodexPlanModeControl(session),
    planActive: state.codexPlanMode,
    planDisabled: unreachable || busy,
    onPlan: () =>
      void apply((id) => useChatStore.getState().setCodexPlanMode(!state.codexPlanMode, id)),
  };
}
