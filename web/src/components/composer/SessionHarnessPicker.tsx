import { useContext, useEffect, useRef, useState } from "react";
import { TriangleAlertIcon, WandSparklesIcon } from "lucide-react";
import { HarnessPicker, HarnessPickerConfigPage, HarnessPickerConfigRow } from "./HarnessPicker";
import { ComposerConfigSections } from "./ComposerConfigSections";
import { ComposerConfigTooltipRows } from "./ComposerControls";
import { DropdownMenuItem, DropdownMenuSeparator } from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { ComposerAgentIcon } from "@/shell/NewChatDialog";
import { useIsMobileViewport } from "@/hooks/useIsMobileViewport";
import { useSessionModelLabel } from "@/hooks/useSessionModelLabel";
import {
  ConversationScopeContext,
  useScopedConversationId,
  useScopedConversationState,
} from "@/components/chat/conversationScope";
import { useChatStore } from "@/store/chatStore";
import { nativeCodingAgentForHarness } from "@/lib/nativeCodingAgents";
import {
  compactModelTriggerLabel,
  formatStatusEffortLabel,
  nativeModelLabel,
} from "@/lib/composerModelLabel";
import { codexEffortLevelsForModel, findNativeModelOption } from "@/lib/codexNativeModels";
import { modelConfigurationSourceRows } from "@/lib/modelConfigurationSource";
import { SMART_ROUTING_LABEL } from "@/lib/agentLabels";
import { fusionOption, isFusionModelUid } from "@/lib/devinFusion";
import { buildFusionSections } from "./fusionSections";
import type { NativeModelPickerKind } from "@/lib/sessionComposerCapabilities";
import type { NativeModelOption } from "@/lib/types";

/**
 * Whether the session surfaces any run-config the gear modal can edit. Shared
 * render guard for the config gear and click-to-open gate for the model/effort
 * label half of the composer's split pill, so both halves stay in lockstep.
 */
function hasSessionConfig({
  showModels,
  showEffort,
}: {
  showModels: boolean;
  showEffort: boolean;
}): boolean {
  return showModels || showEffort;
}

export function SessionHarnessPicker({
  busy,
  busyRef,
  setBusy,
  agentName,
  harnessLabel,
  showModels,
  showEffort,
  effortLevels,
  modelPickerKind,
  supportsModelReset,
  codexModelOptions,
  inferenceConfigured,
  inferenceError,
  modelLabelOptions,
  modelLabelHostId,
  costRoutingEligible,
  disabled,
  openNonce = 0,
}: {
  busy: boolean;
  busyRef: { current: boolean };
  setBusy: (busy: boolean) => void;
  agentName: string | null;
  harnessLabel: string | null;
  showModels: boolean;
  showEffort: boolean;
  effortLevels: readonly string[];
  modelPickerKind: NativeModelPickerKind | null;
  supportsModelReset: boolean;
  codexModelOptions: readonly NativeModelOption[];
  inferenceConfigured?: boolean;
  inferenceError?: string | null;
  modelLabelOptions: readonly NativeModelOption[];
  modelLabelHostId: string | null | undefined;
  costRoutingEligible: boolean;
  disabled: boolean;
  openNonce?: number;
}) {
  const isMobile = useIsMobileViewport();
  const [menuOpen, setMenuOpen] = useState(false);
  const [configOpen, setConfigOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const appliedOpenNonce = useRef(0);
  const conversationId = useScopedConversationId();
  const scopedId = useContext(ConversationScopeContext);
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;
  const sessionHarness = useScopedConversationState((state) => state.sessionHarness);
  const subAgentName = useScopedConversationState((state) => state.subAgentName);
  const pendingModelChange = useScopedConversationState((state) => state.pendingModelChange);
  const sessionModelSeeded = useScopedConversationState((state) => state.sessionModelSeeded);
  const selectedEffort = useSessionEffort();
  const setEffort = (effort: string | null) =>
    scopedId === null
      ? useChatStore.getState().setEffort(effort)
      : useChatStore.getState().setEffort(effort, scopedId);
  const setRouting = (mode: "on" | "off") =>
    scopedId === null
      ? useChatStore.getState().setCostControlMode(mode)
      : useChatStore.getState().setCostControlMode(mode, scopedId);
  const costControlModeOverride = useScopedConversationState(
    (state) => state.costControlModeOverride,
  );
  const routingOn = costRoutingEligible && costControlModeOverride === "on";
  const {
    effectiveModel,
    modelLabel,
    modelLabelLoading,
    modelLabelUnavailable,
    modelOptions,
    pickerSelectedModel,
  } = useResolvedComposerModel(
    modelPickerKind,
    codexModelOptions,
    modelLabelOptions,
    modelLabelHostId,
  );
  const modelSummary = modelLabelLoading
    ? "Loading model…"
    : modelLabelUnavailable
      ? "Model name unavailable"
      : modelLabel;
  const nativeAgent =
    nativeCodingAgentForHarness(sessionHarness) ??
    (modelPickerKind ? nativeCodingAgentForHarness(modelPickerKind + "-native") : undefined);
  const iconAgent = {
    name: nativeAgent?.agentName ?? agentName ?? subAgentName ?? "",
    harness: nativeAgent?.harness ?? sessionHarness,
  };
  const summary = useSessionConfigSummary({
    harnessLabel,
    showModels,
    showEffort,
    codexModelOptions,
    effectiveModel,
    modelLabel: modelSummary,
    costRoutingEligible,
  });
  const configurable = hasSessionConfig({
    showModels,
    showEffort,
  });
  const effortLabel = showEffort && !routingOn ? formatStatusEffortLabel(selectedEffort) : null;
  const label = routingOn
    ? SMART_ROUTING_LABEL
    : modelLabelLoading
      ? ""
      : compactModelTriggerLabel(
          modelSummary ?? nativeAgent?.displayName ?? harnessLabel ?? "Session",
        );
  const availableEfforts =
    modelPickerKind === "codex"
      ? codexEffortLevelsForModel(codexModelOptions, pickerSelectedModel)
      : effortLevels;
  useEffect(() => {
    if (!openNonce || openNonce === appliedOpenNonce.current) return;
    appliedOpenNonce.current = openNonce;
    if (!disabled && configurable) {
      setMenuOpen(true);
      setConfigOpen(true);
    }
  }, [openNonce, disabled, configurable]);
  useEffect(() => {
    setMenuOpen(false);
    setConfigOpen(false);
    setError(null);
  }, [conversationId]);
  const apply = async (change: () => Promise<unknown>) => {
    if (disabled || busyRef.current || pendingModelChange !== null) return;
    busyRef.current = true;
    setBusy(true);
    setError(null);
    const sourceSessionId = conversationId;
    try {
      await change();
    } catch (failure) {
      if (conversationIdRef.current === sourceSessionId)
        setError(
          failure instanceof Error ? failure.message : "Unable to update session configuration",
        );
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };
  const selectModel = (modelId: string | null) =>
    void apply(async () => {
      const store = useChatStore.getState();
      const sourceSessionId = conversationId;
      await store.setModel(modelId, {
        expectConfirmation: modelPickerKind === "claude" || modelPickerKind === "codex",
        ...(scopedId === null ? {} : { conversationId: scopedId }),
      });
      if (conversationIdRef.current !== sourceSessionId) return;
      if (
        modelPickerKind === "codex" &&
        selectedEffort !== null &&
        !codexEffortLevelsForModel(codexModelOptions, modelId).includes(selectedEffort)
      )
        await setEffort(null);
      if (costRoutingEligible && routingOn && conversationIdRef.current === sourceSessionId)
        await setRouting("off");
    });
  // Devin Fusion: the composed `fusion-…` id is the model; the lead effort is
  // baked in, so it carries no separate reasoning effort.
  const composerFusionOption = fusionOption(modelOptions);
  const composerFusion = composerFusionOption?.fusion;
  const fusionSelected = composerFusion !== undefined && isFusionModelUid(pickerSelectedModel);
  const selectFusionModel = (modelUid: string) =>
    void apply(async () => {
      const store = useChatStore.getState();
      const sourceSessionId = conversationId;
      await store.setModel(modelUid, {
        expectConfirmation: false,
        ...(scopedId === null ? {} : { conversationId: scopedId }),
      });
      if (conversationIdRef.current !== sourceSessionId) return;
      if (selectedEffort !== null) await setEffort(null);
    });
  const configContent = (
    <>
      {costRoutingEligible && showModels && (
        <>
          <DropdownMenuItem
            disabled={busy || pendingModelChange !== null}
            onSelect={() =>
              void apply(() =>
                useChatStore
                  .getState()
                  .setCostControlMode(routingOn ? "off" : "on", conversationId ?? undefined),
              )
            }
            data-active={routingOn ? "true" : undefined}
            className="items-center text-13 data-[active=true]:bg-muted data-[active=true]:text-foreground dark:data-[active=true]:bg-muted/50"
          >
            <WandSparklesIcon className="size-4" />
            {SMART_ROUTING_LABEL}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
        </>
      )}
      <ComposerConfigSections
        models={
          showModels
            ? {
                testId: "composer-agent-models",
                header: "Models",
                leading:
                  (inferenceConfigured && inferenceError) || modelOptions.length === 0 ? (
                    <div className="px-2 py-1 text-xs text-muted-foreground" role="status">
                      {inferenceError ?? "No usable models are available for this session."}
                    </div>
                  ) : undefined,
                choices: [
                  ...(supportsModelReset &&
                  !inferenceConfigured &&
                  !modelOptions.some((model) => model.isDefault)
                    ? [
                        {
                          key: "__default__",
                          label: "Default",
                          checked: !routingOn && pickerSelectedModel === null,
                          disabled: busy || pendingModelChange !== null || !!inferenceError,
                          onSelect: () => selectModel(null),
                          testId: "composer-agent-model-default",
                        },
                      ]
                    : []),
                  ...modelOptions.map((model) => ({
                    key: model.id,
                    label: nativeModelLabel(model),
                    checked:
                      !routingOn &&
                      (composerFusion !== undefined && model.id === composerFusionOption?.id
                        ? isFusionModelUid(pickerSelectedModel)
                        : model.id === pickerSelectedModel),
                    disabled: busy || pendingModelChange !== null || !!inferenceError,
                    onSelect: () =>
                      composerFusion !== undefined && model.id === composerFusionOption?.id
                        ? selectFusionModel(composerFusion.default)
                        : selectModel(supportsModelReset && model.isDefault ? null : model.id),
                    testId: `composer-agent-model-${model.id}`,
                    className: "whitespace-normal break-words",
                    data: { "data-model-id": model.id },
                  })),
                  ...(pickerSelectedModel &&
                  !isFusionModelUid(pickerSelectedModel) &&
                  !modelOptions.some((model) => model.id === pickerSelectedModel)
                    ? [
                        {
                          key: "__current__",
                          label: `${modelSummary ?? "Default"} (current)`,
                          checked: !routingOn,
                          disabled: true,
                          className: "whitespace-normal break-words",
                          data: { "data-model-id": pickerSelectedModel },
                        },
                      ]
                    : []),
                ],
              }
            : undefined
        }
        efforts={
          showEffort && availableEfforts.length > 0
            ? {
                testId: "composer-agent-efforts",
                header: modelPickerKind === "pi" ? "Thinking level" : "Effort",
                choices: availableEfforts.map((effort) => ({
                  key: effort,
                  label: formatStatusEffortLabel(effort) ?? effort,
                  checked: !routingOn && effort === selectedEffort,
                  disabled: routingOn || busy || pendingModelChange !== null,
                  onSelect: () => void apply(() => setEffort(effort)),
                  testId: `composer-agent-effort-${effort}`,
                  data: { "data-effort-level": effort },
                })),
              }
            : undefined
        }
        extra={
          composerFusion !== undefined && fusionSelected && !routingOn
            ? buildFusionSections({
                descriptor: composerFusion,
                modelUid: pickerSelectedModel ?? composerFusion.default,
                testIdPrefix: "composer-agent",
                onChange: selectFusionModel,
                disabled: busy || pendingModelChange !== null,
              })
            : undefined
        }
      />
    </>
  );
  return (
    <>
      <HarnessPicker
        open={menuOpen}
        onOpenChange={(next) => {
          if (!next || (!disabled && !busy && configurable)) setMenuOpen(next);
          if (!next) setConfigOpen(false);
        }}
        trigger={{
          label: "Configure session",
          model: label,
          effort: effortLabel ?? undefined,
          icon: <ComposerAgentIcon agent={iconAgent} />,
          disabled: busy || !configurable,
          "aria-disabled": disabled || busy || !configurable,
          className: disabled ? "cursor-default opacity-50" : undefined,
          testIdPrefix: "composer",
          "data-testid": "composer-config-gear",
          loading: modelLabelLoading && !routingOn,
          pending:
            (sessionModelSeeded || pendingModelChange !== null) &&
            (modelPickerKind === "claude" || modelPickerKind === "codex"),
        }}
        tooltip={<ComposerConfigTooltipRows rows={summary} />}
        tooltipTestId="composer-config-gear-tooltip"
        testId="composer-agent-menu"
      >
        {isMobile && configOpen ? (
          <HarnessPickerConfigPage
            backTestId="composer-agent-config-back"
            testId="composer-agent-config-menu"
            onBack={() => setConfigOpen(false)}
          >
            {configContent}
          </HarnessPickerConfigPage>
        ) : (
          <HarnessPickerConfigRow
            label={nativeAgent?.displayName ?? harnessLabel ?? "Session"}
            value={routingOn ? SMART_ROUTING_LABEL : (modelSummary ?? "Default")}
            open={configOpen}
            onOpenChange={setConfigOpen}
            isMobile={isMobile}
            disabled={busy || pendingModelChange !== null}
            valueTestId="composer-agent-model-summary"
            testId="composer-agent-edit"
            configTestId="composer-agent-config-menu"
          >
            {configContent}
          </HarnessPickerConfigRow>
        )}
      </HarnessPicker>
      {error && (
        <TooltipProvider delayDuration={0}>
          <Tooltip>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-label={`Couldn't update configuration: ${error}`}
                className="flex size-7 shrink-0 items-center justify-center rounded-lg text-destructive hover:bg-destructive/10"
                data-testid="composer-config-error"
              >
                <TriangleAlertIcon className="size-4" aria-hidden="true" />
              </button>
            </TooltipTrigger>
            <TooltipContent
              side="top"
              className="w-72 max-w-[calc(100vw-2rem)] flex-col items-start gap-1 rounded-lg border border-border bg-popover p-3 text-popover-foreground shadow-menu"
              data-testid="composer-config-error-tooltip"
            >
              <strong className="font-medium">Couldn’t update configuration</strong>
              <span className="text-xs leading-5 text-muted-foreground">
                {error} Try again, or reconnect the session if the problem continues.
              </span>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      )}
    </>
  );
}

/**
 * Label/value rows summarizing the session's live run-config, for the gear
 * icon's hover tooltip. Mirrors the new-session summary but with in-session
 * values. The Permissions row lives in the modal itself, not this summary.
 */
function useSessionConfigSummary({
  harnessLabel,
  showModels,
  showEffort,
  codexModelOptions,
  effectiveModel,
  modelLabel,
  costRoutingEligible,
}: {
  harnessLabel: string | null;
  showModels: boolean;
  showEffort: boolean;
  codexModelOptions: readonly NativeModelOption[];
  effectiveModel: string | null;
  modelLabel: string | null;
  costRoutingEligible: boolean;
}): { label: string; value: string }[] {
  const selectedEffort = useSessionEffort();
  const costControlModeOverride = useScopedConversationState((s) => s.costControlModeOverride);
  const routingOn = costRoutingEligible && costControlModeOverride === "on";

  const rows: { label: string; value: string }[] = [];
  if (harnessLabel) rows.push({ label: "Harness", value: harnessLabel });
  if (showModels) {
    rows.push({
      label: "Model",
      value: routingOn ? SMART_ROUTING_LABEL : (modelLabel ?? "Default"),
    });
  }
  // Suppress Effort while routing is on: the router picks the model and its
  // effort per turn, so a pinned effort doesn't apply and would mislead.
  if (showEffort && !routingOn) {
    const effortValue = formatStatusEffortLabel(selectedEffort);
    if (effortValue) rows.push({ label: "Effort", value: effortValue });
  }
  if (!routingOn) {
    const source =
      findNativeModelOption(codexModelOptions, effectiveModel)?.source ??
      codexModelOptions.find((option) => option.source)?.source;
    rows.push(...modelConfigurationSourceRows(source));
  }
  return rows;
}

/**
 * The effort this conversation is actually at.
 *
 * `sessionReasoningEffort` is conversation-scoped, so two live conversations at
 * different efforts each read their own.
 */
function useSessionEffort(): string | null {
  return useScopedConversationState((s) => s.sessionReasoningEffort);
}

/**
 * Resolve the session's live model + its picker option list from the store,
 * per harness family. Shared by the AgentPicker trigger, the gear config
 * modal, and the gear hover summary so all three agree on what "the current
 * model" is (the resolution differs by wrapper — see the inline notes).
 *
 * @param modelPickerKind Native picker family, or ``null`` for SDK/bundle.
 * @param codexModelOptions Server-provided model options (codex/cursor/…).
 */
function useResolvedComposerModel(
  modelPickerKind: NativeModelPickerKind | null,
  codexModelOptions: readonly NativeModelOption[],
  modelLabelOptions: readonly NativeModelOption[],
  hostId: string | null | undefined,
) {
  const sessionId = useScopedConversationId();
  const agentId = useScopedConversationState((s) => s.boundAgentId);
  const harness = useScopedConversationState((s) => s.sessionHarness);
  const sessionModelOverride = useScopedConversationState((s) => s.sessionModelOverride);
  const sessionModelSeeded = useScopedConversationState((s) => s.sessionModelSeeded);
  const llmModel = useScopedConversationState((s) => s.llmModel);
  const nativeVendorOwnsModel = useScopedConversationState((s) => s.nativeVendorOwnsModel);

  // Native model pickers populate from the snapshot's runner-backed
  // ``model_options`` field. Claude's rows are the aliases pinned to the
  // launch-time Databricks catalog; Codex carries richer effort metadata.
  const usesServerModelOptions =
    modelPickerKind === "claude" ||
    modelPickerKind === "codex" ||
    modelPickerKind === "cursor" ||
    modelPickerKind === "kiro" ||
    modelPickerKind === "pi" ||
    modelPickerKind === "opencode" ||
    modelPickerKind === "devin" ||
    modelPickerKind === "acp" ||
    modelPickerKind === "configured";
  const modelOptions: readonly {
    id: string;
    model?: string;
    label?: string;
    displayName?: string;
    isDefault?: boolean;
  }[] = usesServerModelOptions ? codexModelOptions : [];
  const isNativeModelPicker = modelPickerKind !== null;

  // The harness's own report is the display authority for claude-/codex-
  // native sessions: `llmModel` carries the verbatim reported model (the
  // launch's own report, or an in-pane switch), and the chip, the gear
  // highlight, and the hover summary all resolve from it alone. The user's
  // request (`sessionModelOverride`) is input, never display state — rendering
  // a request as if it were truth is exactly how a record/pane divergence hides.
  const isReportedModelPicker = modelPickerKind === "claude" || modelPickerKind === "codex";
  // The row the reported model maps to: its catalog row when one matches
  // exactly (by id or wire model), else the raw reported value itself — the
  // modal appends that as its own honest row rather than relabeling it onto
  // a same-family row of a different generation.
  const reportedRowId =
    isReportedModelPicker && llmModel
      ? (findNativeModelOption(codexModelOptions, llmModel)?.id ?? llmModel)
      : null;
  // Before the harness has reported anything (a routed session whose pane
  // has not started, a reload of one), the gear seeds from the session's
  // own REQUEST so the pick the user (or the router) made is what the row
  // offers to edit — a request is never display truth, but it is the draft.
  // The moment a report exists it wins, so a request the pane never took
  // can't masquerade as the active model.
  const requestedRowId =
    isReportedModelPicker && sessionModelOverride
      ? (findNativeModelOption(codexModelOptions, sessionModelOverride)?.id ?? sessionModelOverride)
      : null;
  // cursor mirrors its live TUI model into ``model_override``; kiro sets it
  // on a web pick (which also drives a live ``/model`` switch); opencode/pi
  // mirror both ways into ``model_override``. Those wrappers keep their
  // override-derived surface until they adopt reported-model semantics.
  // SDK/bundle agents (no native picker) resolve the session override or the
  // bound default.
  const pickerSelectedModel = isReportedModelPicker
    ? (reportedRowId ?? requestedRowId)
    : (sessionModelOverride ?? (modelPickerKind === "configured" ? llmModel : null));
  const effectiveModel = sessionModelSeeded
    ? (sessionModelOverride ?? llmModel)
    : nativeVendorOwnsModel
      ? modelPickerKind === "cursor" || modelPickerKind === "kiro"
        ? sessionModelOverride
        : modelPickerKind === "opencode" || modelPickerKind === "pi" || modelPickerKind === "devin"
          ? (sessionModelOverride ?? llmModel)
          : null
      : isReportedModelPicker
        ? llmModel
        : (sessionModelOverride ?? llmModel);
  const {
    label: modelLabel,
    loading: modelLabelLoading,
    unavailable: modelLabelUnavailable,
  } = useSessionModelLabel(
    { sessionId, hostId: hostId ?? null, agentId, harness },
    effectiveModel,
    modelLabelOptions,
    usesServerModelOptions,
    hostId !== undefined &&
      !sessionModelSeeded &&
      (!isReportedModelPicker || effectiveModel === llmModel),
    codexModelOptions,
  );
  return {
    llmModel,
    usesServerModelOptions,
    modelOptions,
    isNativeModelPicker,
    pickerSelectedModel,
    effectiveModel,
    modelLabel,
    modelLabelLoading,
    modelLabelUnavailable,
  };
}
