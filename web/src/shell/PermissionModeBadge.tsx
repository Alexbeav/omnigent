import { ShieldAlertIcon, ShieldCheckIcon, ShieldIcon } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  CLAUDE_NATIVE_SWITCHABLE_PERMISSION_MODES,
  claudePermissionModeLabel,
} from "@/lib/claudePermissionMode";
import { cn } from "@/lib/utils";
import { useChatStore } from "@/store/chatStore";

/**
 * Header badge for the claude-native approval mode, sitting next to the host
 * icon. It reads the mode the session is actually in and switches it in place,
 * so the mode is visible without opening the composer's config panel.
 *
 * Self-contained: reads the chat store directly, like `PresenceAvatars`, so
 * the header's prop surface stays untouched.
 *
 * Renders nothing when the mode is unknown. Claude only reports its mode in
 * some pane states, and a settings-file `permissions.defaultMode` boots a
 * session into a mode the launch args never mention, so any guess would
 * display a mode the session is not in.
 */
export function PermissionModeBadge() {
  const mode = useChatStore((s) => s.claudePermissionMode);
  const setMode = useChatStore((s) => s.setClaudePermissionMode);

  // "" is the store's unknown mode. Fail closed and render nothing.
  if (mode === "") return null;

  const label = claudePermissionModeLabel(mode);
  // "Bypass permissions" and "Don't ask" run without prompting, so they get a
  // warning glyph rather than the neutral shield.
  const promptsDisabled = mode === "bypassPermissions" || mode === "dontAsk";
  const Icon = mode === "plan" ? ShieldIcon : promptsDisabled ? ShieldAlertIcon : ShieldCheckIcon;

  return (
    <DropdownMenu>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex shrink-0">
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                aria-label={`Approval mode: ${label}`}
                data-testid="header-permission-mode"
                data-permission-mode={mode}
                className={cn(
                  "inline-flex h-5 shrink-0 items-center gap-1 rounded-full border px-1.5 text-[10px] transition-colors",
                  promptsDisabled
                    ? "border-amber-500/40 text-amber-600 hover:bg-amber-500/10 dark:text-amber-400"
                    : "border-border text-muted-foreground hover:bg-accent hover:text-foreground",
                )}
              >
                <Icon className="size-3 shrink-0" />
                <span className="truncate">{label}</span>
              </button>
            </DropdownMenuTrigger>
          </span>
        </TooltipTrigger>
        <TooltipContent side="bottom">
          <div className="flex flex-col gap-0.5">
            <span className="font-semibold">Approval mode: {label}</span>
            <span className="text-muted-foreground">How much the agent asks before acting.</span>
          </div>
        </TooltipContent>
      </Tooltip>
      <DropdownMenuContent align="start" className="min-w-52">
        {CLAUDE_NATIVE_SWITCHABLE_PERMISSION_MODES.map((option) => (
          <DropdownMenuItem
            key={option.value}
            data-testid={`permission-mode-option-${option.value}`}
            // Disabled rather than hidden: the current mode stays visible in
            // the list, so the closed trigger and the open menu agree.
            disabled={option.value === mode}
            onSelect={() => {
              if (option.value !== mode) void setMode(option.value);
            }}
          >
            <span className="flex flex-col items-start">
              <span>{option.label}</span>
              <span className="text-muted-foreground text-xs">{option.description}</span>
            </span>
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
