import { type CSSProperties, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { ExternalLinkIcon, PanelRightOpenIcon, XIcon } from "lucide-react";
import type { Conversation } from "@/hooks/useConversations";
import { SideChatPane } from "@/components/chat/SideChatPane";
import { Button } from "@/components/ui/button";
import { sessionNavigationSearch } from "@/lib/sessionNavigation";

export const MAX_CHAT_PANES = 3;

export function normalizePaneIds(primaryId: string | undefined, raw: string | null): string[] {
  const seen = new Set(primaryId ? [primaryId] : []);
  return (raw ?? "")
    .split(",")
    .map((id) => id.trim())
    .filter((id) => id !== "" && !seen.has(id) && seen.add(id))
    .slice(0, MAX_CHAT_PANES - 1);
}

export function buildPanePopoutUrl(
  currentHref: string,
  conversationId: string,
  rebasePath: (path: string) => string,
): URL {
  const url = new URL(currentHref);
  url.pathname = rebasePath(`/c/${encodeURIComponent(conversationId)}`);
  url.search = sessionNavigationSearch(url.search);
  url.searchParams.delete("panes");
  url.hash = "";
  return url;
}

function sessionLabel(conversations: readonly Conversation[], id: string): string {
  return conversations.find((conversation) => conversation.id === id)?.title ?? id;
}

function ResizableChatPane({ children, label }: { children: ReactNode; label: string }) {
  const [width, setWidth] = useState<number | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const constrain = (requested: number) => {
    const section = sectionRef.current;
    const container = section?.parentElement;
    if (!container) return Math.max(320, requested);
    const reserved = Array.from(container.children)
      .filter((sibling) => sibling !== section && sibling.tagName === "SECTION")
      .reduce((total, sibling) => {
        const pane = sibling as HTMLElement;
        return total + (pane.style.flexBasis ? pane.offsetWidth : 320);
      }, 0);
    return Math.max(320, Math.min(requested, container.clientWidth - reserved));
  };
  useEffect(() => {
    const move = (event: MouseEvent) => {
      if (!drag.current) return;
      setWidth(constrain(drag.current.width + drag.current.x - event.clientX));
    };
    const stop = () => {
      drag.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
      stop();
    };
  }, []);
  const resize = (delta: number) =>
    setWidth(constrain((sectionRef.current?.offsetWidth ?? 320) + delta));
  return (
    <section
      ref={sectionRef}
      className="relative hidden min-h-0 min-w-80 flex-1 flex-col overflow-hidden border-l border-border bg-background md:flex"
      aria-label={label}
      style={width === null ? undefined : { flex: `0 0 ${width}px` }}
    >
      <div
        role="separator"
        aria-label={`Resize ${label}`}
        aria-orientation="vertical"
        tabIndex={0}
        className="absolute inset-y-0 left-0 z-20 w-1 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50"
        onMouseDown={(event) => {
          event.preventDefault();
          drag.current = {
            x: event.clientX,
            width: event.currentTarget.parentElement!.offsetWidth,
          };
          document.body.style.cursor = "col-resize";
          document.body.style.userSelect = "none";
        }}
        onKeyDown={(event) => {
          if (event.key === "ArrowLeft") resize(20);
          else if (event.key === "ArrowRight") resize(-20);
          else return;
          event.preventDefault();
        }}
      />
      {children}
    </section>
  );
}

export function ConversationPanes({
  primary,
  header,
  primaryId,
  paneIds,
  conversations,
  onAdd,
  onClose,
  onPopout,
}: {
  primary: ReactNode;
  header?: ReactNode;
  primaryId?: string;
  paneIds: string[];
  conversations: readonly Conversation[];
  onAdd: (id: string) => void;
  onClose: (id: string) => void;
  onPopout: (id: string) => void;
}) {
  const openIds = useMemo(() => new Set([primaryId, ...paneIds]), [primaryId, paneIds]);
  const choices = conversations.filter((conversation) => !openIds.has(conversation.id));

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-x-auto" data-testid="conversation-panes">
      <section
        className="relative flex min-h-0 min-w-0 flex-1 flex-col md:min-w-80"
        aria-label="Primary chat"
        style={{ "--workspace-panel-offset": "2.75rem" } as CSSProperties}
      >
        {header}
        {primary}
        {primaryId && (
          <Button
            type="button"
            size="icon-sm"
            variant="ghost"
            className="absolute top-2 right-2 z-50 hidden md:inline-flex"
            aria-label="Open primary chat in a new window"
            onClick={() => onPopout(primaryId)}
          >
            <ExternalLinkIcon />
          </Button>
        )}
      </section>
      {paneIds.map((id) => (
        <ResizableChatPane key={id} label={`Chat: ${sessionLabel(conversations, id)}`}>
          <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-3">
            <span className="min-w-0 flex-1 truncate text-sm font-medium">
              {sessionLabel(conversations, id)}
            </span>
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label={`Open ${sessionLabel(conversations, id)} in a new window`}
              onClick={() => onPopout(id)}
            >
              <ExternalLinkIcon />
            </Button>
            <Button
              type="button"
              size="icon-sm"
              variant="ghost"
              aria-label={`Close ${sessionLabel(conversations, id)} pane`}
              onClick={() => onClose(id)}
            >
              <XIcon />
            </Button>
          </header>
          <div className="min-h-0 flex-1">
            <SideChatPane childId={id} showFullHistory />
          </div>
        </ResizableChatPane>
      ))}
      {paneIds.length < MAX_CHAT_PANES - 1 && choices.length > 0 && (
        <label className="absolute right-3 bottom-3 z-50 hidden items-center gap-1 rounded-md border border-border bg-background px-2 shadow-sm md:flex">
          <PanelRightOpenIcon className="size-4" aria-hidden="true" />
          <span className="sr-only">Add chat pane</span>
          <select
            aria-label="Add chat pane"
            className="h-8 max-w-36 bg-transparent text-sm outline-none"
            value=""
            onChange={(event) => {
              if (event.target.value) onAdd(event.target.value);
            }}
          >
            <option value="">Add pane…</option>
            {choices.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>
                {conversation.title ?? conversation.id}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}
