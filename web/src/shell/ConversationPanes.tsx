import {
  type CSSProperties,
  type PointerEventHandler,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { ExternalLinkIcon, XIcon } from "lucide-react";
import type { Conversation } from "@/hooks/useConversations";
import { SideChatPane } from "@/components/chat/SideChatPane";
import { Button } from "@/components/ui/button";
import { sessionNavigationSearch } from "@/lib/sessionNavigation";
import { isChatDetachPoint } from "./chatDetach";

export const MAX_CHAT_PANES = 3;

export function normalizePaneIds(primaryId: string | undefined, raw: string | null): string[] {
  const seen = new Set(primaryId ? [primaryId] : []);
  return (raw ?? "")
    .split(",")
    .map((id) => id.trim())
    .filter((id) => id !== "" && !seen.has(id) && seen.add(id))
    .slice(0, MAX_CHAT_PANES - 1);
}

export function normalizePaneOrder(
  primaryId: string | undefined,
  paneIds: readonly string[],
  raw: string | null,
): string[] {
  const available = new Set([primaryId, ...paneIds].filter((id): id is string => Boolean(id)));
  const ordered = (raw ?? "")
    .split(",")
    .map((id) => id.trim())
    .filter((id, index, ids) => available.has(id) && ids.indexOf(id) === index);
  for (const id of available) if (!ordered.includes(id)) ordered.push(id);
  return ordered;
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
  url.searchParams.delete("paneOrder");
  url.hash = "";
  return url;
}

function sessionLabel(conversations: readonly Conversation[], id: string): string {
  return conversations.find((conversation) => conversation.id === id)?.title ?? id;
}

function usePaneHeaderDetach(onPopout: () => void) {
  const drag = useRef<{ pointerId: number; x: number; y: number; target: HTMLElement } | null>(
    null,
  );
  const cancel = () => {
    const active = drag.current;
    drag.current = null;
    if (active?.target.hasPointerCapture?.(active.pointerId)) {
      active.target.releasePointerCapture?.(active.pointerId);
    }
  };
  useEffect(() => {
    const cancelOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && drag.current) cancel();
    };
    window.addEventListener("keydown", cancelOnEscape);
    return () => window.removeEventListener("keydown", cancelOnEscape);
  });
  const onPointerDown: PointerEventHandler<HTMLElement> = (event) => {
    if (
      event.button !== 0 ||
      !(event.target as Element).closest("[data-pane-drag-handle]") ||
      (event.target as Element).closest("button, select, input, textarea, a")
    )
      return;
    event.preventDefault();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      target: event.currentTarget,
    };
  };
  const onPointerUp: PointerEventHandler<HTMLElement> = (event) => {
    const start = drag.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const moved = Math.hypot(event.clientX - start.x, event.clientY - start.y) >= 5;
    drag.current = null;
    if (moved && isChatDetachPoint(event.clientX, event.clientY)) onPopout();
  };
  return {
    dragProps: {
      onPointerDown,
      onPointerUp,
      onPointerCancel: cancel,
      onLostPointerCapture: cancel,
    },
  };
}

function ResizableChatPane({
  children,
  label,
  paneId,
  onPopout,
  active,
  onActivate,
  width,
  paneIndex,
  onResize,
}: {
  children: ReactNode;
  label: string;
  paneId: string;
  onPopout: () => void;
  active?: boolean;
  onActivate?: () => void;
  width: number | null;
  paneIndex: number;
  onResize: (index: number, width: number) => void;
}) {
  const setWidth = useCallback((next: number) => onResize(paneIndex, next), [onResize, paneIndex]);
  const sectionRef = useRef<HTMLElement>(null);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const { dragProps } = usePaneHeaderDetach(onPopout);
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
  }, [setWidth]);
  const resize = (delta: number) =>
    setWidth(constrain((sectionRef.current?.offsetWidth ?? 320) + delta));
  return (
    <section
      ref={sectionRef}
      data-pane-id={paneId}
      data-active-pane={active}
      onPointerDownCapture={onActivate}
      onFocusCapture={onActivate}
      className="relative hidden min-h-0 min-w-80 flex-1 flex-col overflow-hidden border-l border-border bg-background md:flex"
      aria-label={label}
      style={width === null ? undefined : { flex: `0 0 ${width}px` }}
      {...dragProps}
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
      {active && (
        <div className="pointer-events-none absolute inset-0 z-30 rounded-sm ring-1 ring-inset ring-blue-500/60" />
      )}
    </section>
  );
}

export function ConversationPanes({
  primary,
  header,
  primaryId,
  paneOrder,
  activePaneId,
  onActivate,
  conversations,
  onClose,
  onPopout,
}: {
  primary: ReactNode;
  header?: ReactNode;
  primaryId?: string;
  paneOrder: string[];
  activePaneId?: string;
  onActivate?: (id: string) => void;
  conversations: readonly Conversation[];
  onClose: (id: string) => void;
  onPopout: (id: string) => void;
}) {
  // Widths belong to the visible slots, so replacing a chat keeps its divider in place.
  const [widths, setWidths] = useState<Record<number, number>>({});
  const resizePane = useCallback((index: number, width: number) => {
    setWidths((previous) => ({ ...previous, [index]: width }));
  }, []);
  const primaryDetach = usePaneHeaderDetach(() => {
    if (primaryId) onPopout(primaryId);
  });

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-x-auto" data-testid="conversation-panes">
      {paneOrder.map((id, index) =>
        id === primaryId ? (
          <section
            key={id}
            data-pane-id={id}
            data-active-pane={activePaneId === id}
            onPointerDownCapture={() => onActivate?.(id)}
            onFocusCapture={() => onActivate?.(id)}
            className="relative flex min-h-0 min-w-0 flex-1 flex-col md:min-w-80"
            aria-label="Primary chat"
            style={
              {
                "--workspace-panel-offset": "2.75rem",
                ...(widths[index] === undefined ? {} : { flex: `0 0 ${widths[index]}px` }),
              } as CSSProperties
            }
            {...primaryDetach.dragProps}
          >
            <div data-pane-drag-handle className="contents">
              {header}
            </div>
            {primary}
            {paneOrder.length > 1 && activePaneId === id && (
              <div className="pointer-events-none absolute inset-0 z-30 hidden rounded-sm ring-1 ring-inset ring-blue-500/60 md:block" />
            )}
          </section>
        ) : (
          <ResizableChatPane
            key={id}
            label={`Chat: ${sessionLabel(conversations, id)}`}
            paneId={id}
            onPopout={() => onPopout(id)}
            active={activePaneId === id}
            onActivate={() => onActivate?.(id)}
            width={widths[index] ?? null}
            paneIndex={index}
            onResize={resizePane}
          >
            <header
              data-pane-drag-handle
              className="flex h-12 shrink-0 cursor-grab select-none items-center gap-2 border-b border-border px-3 active:cursor-grabbing"
            >
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
        ),
      )}
    </div>
  );
}
