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

function ChatPane({
  children,
  label,
  paneId,
  onPopout,
  active,
  onActivate,
  width,
  primary,
  resizeHandle,
}: {
  children: ReactNode;
  label: string;
  paneId: string;
  onPopout: () => void;
  active?: boolean;
  onActivate?: () => void;
  width?: number;
  primary: boolean;
  resizeHandle?: ReactNode;
}) {
  const { dragProps } = usePaneHeaderDetach(onPopout);
  return (
    <section
      data-pane-id={paneId}
      data-active-pane={active}
      onPointerDownCapture={onActivate}
      onFocusCapture={onActivate}
      className={
        "relative min-h-0 flex-1 flex-col md:min-w-80 md:[flex:var(--pane-flex)] " +
        (primary
          ? "flex min-w-0"
          : "hidden min-w-80 overflow-hidden border-l border-border bg-background md:flex")
      }
      aria-label={label}
      style={
        {
          "--workspace-panel-offset": primary ? "2.75rem" : undefined,
          "--pane-flex": width === undefined ? "1 1 0%" : `${width} 1 ${width}px`,
        } as CSSProperties
      }
      {...dragProps}
    >
      {resizeHandle}
      {children}
      {active && (
        <div className="pointer-events-none absolute inset-0 z-30 hidden rounded-sm ring-1 ring-inset ring-blue-500/60 md:block" />
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
  const [widths, setWidths] = useState<number[]>([]);
  const panesRef = useRef<HTMLDivElement>(null);
  const drag = useRef<{ index: number; x: number; widths: number[] } | null>(null);
  const readWidths = useCallback(
    () => Array.from(panesRef.current?.children ?? [], (pane) => (pane as HTMLElement).offsetWidth),
    [],
  );
  const resizeBoundary = useCallback((index: number, delta: number, sizes: number[]) => {
    if (index < 1 || index >= sizes.length) return;
    const total = sizes[index - 1] + sizes[index];
    const left = Math.max(320, Math.min(sizes[index - 1] + delta, total - 320));
    const next = [...sizes];
    next[index - 1] = left;
    next[index] = total - left;
    setWidths(next);
  }, []);
  useEffect(() => {
    const move = (event: MouseEvent) => {
      const start = drag.current;
      if (start) resizeBoundary(start.index, event.clientX - start.x, start.widths);
    };
    const stop = () => {
      if (!drag.current) return;
      drag.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", stop);
    window.addEventListener("blur", stop);
    return () => {
      window.removeEventListener("mousemove", move);
      window.removeEventListener("mouseup", stop);
      window.removeEventListener("blur", stop);
      stop();
    };
  }, [resizeBoundary]);

  return (
    <div
      ref={panesRef}
      className="flex min-h-0 min-w-0 flex-1 overflow-x-auto"
      data-testid="conversation-panes"
    >
      {paneOrder.map((id, index) => {
        const isPrimary = id === primaryId;
        const label = isPrimary ? "Primary chat" : `Chat: ${sessionLabel(conversations, id)}`;
        return (
          <ChatPane
            key={id}
            label={label}
            paneId={id}
            primary={isPrimary}
            onPopout={() => onPopout(id)}
            active={paneOrder.length > 1 && activePaneId === id}
            onActivate={() => onActivate?.(id)}
            width={widths[index]}
            resizeHandle={
              index > 0 && (
                <div
                  role="separator"
                  aria-label={`Resize ${label}`}
                  aria-orientation="vertical"
                  tabIndex={0}
                  className="absolute inset-y-0 left-0 z-20 hidden w-1.5 cursor-col-resize transition-colors hover:bg-primary/30 active:bg-primary/50 md:block"
                  onMouseDown={(event) => {
                    event.preventDefault();
                    drag.current = { index, x: event.clientX, widths: readWidths() };
                    document.body.style.cursor = "col-resize";
                    document.body.style.userSelect = "none";
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
                    event.preventDefault();
                    resizeBoundary(index, event.key === "ArrowLeft" ? -20 : 20, readWidths());
                  }}
                />
              )
            }
          >
            {isPrimary ? (
              <>
                <div data-pane-drag-handle className="contents">
                  {header}
                </div>
                {primary}
              </>
            ) : (
              <>
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
              </>
            )}
          </ChatPane>
        );
      })}
    </div>
  );
}
