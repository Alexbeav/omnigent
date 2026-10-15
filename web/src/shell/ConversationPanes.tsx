import {
  type CSSProperties,
  type PointerEventHandler,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";
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
  const [detaching, setDetaching] = useState(false);
  const cancel = () => {
    const active = drag.current;
    drag.current = null;
    setDetaching(false);
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
  const onPointerMove: PointerEventHandler<HTMLElement> = (event) => {
    const start = drag.current;
    if (!start || start.pointerId !== event.pointerId) return;
    if (!detaching && Math.hypot(event.clientX - start.x, event.clientY - start.y) >= 5) {
      setDetaching(true);
    }
  };
  const onPointerUp: PointerEventHandler<HTMLElement> = (event) => {
    const start = drag.current;
    if (!start || start.pointerId !== event.pointerId) return;
    const moved = Math.hypot(event.clientX - start.x, event.clientY - start.y) >= 5;
    drag.current = null;
    setDetaching(false);
    if (moved && isChatDetachPoint(event.clientX, event.clientY)) onPopout();
  };
  return {
    dragProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel: cancel,
      onLostPointerCapture: cancel,
    },
    detachTarget:
      detaching &&
      createPortal(
        <div
          data-testid="chat-detach-target"
          className="pointer-events-none fixed top-0 right-0 bottom-0 z-[80] flex w-12 items-center justify-center border-l-2 border-dashed border-primary bg-primary/15 text-xs font-medium text-primary [writing-mode:vertical-rl]"
        >
          Drop to open in new window
        </div>,
        document.body,
      ),
  };
}

function ResizableChatPane({
  children,
  label,
  paneId,
  onPopout,
}: {
  children: ReactNode;
  label: string;
  paneId: string;
  onPopout: () => void;
}) {
  const [width, setWidth] = useState<number | null>(null);
  const sectionRef = useRef<HTMLElement>(null);
  const drag = useRef<{ x: number; width: number } | null>(null);
  const { dragProps, detachTarget } = usePaneHeaderDetach(onPopout);
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
      data-pane-id={paneId}
      className="relative hidden min-h-0 min-w-80 flex-1 flex-col overflow-hidden border-l border-border bg-background md:flex"
      aria-label={label}
      style={width === null ? undefined : { flex: `0 0 ${width}px` }}
      {...dragProps}
    >
      {detachTarget}
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
  paneOrder,
  conversations,
  onClose,
  onPopout,
}: {
  primary: ReactNode;
  header?: ReactNode;
  primaryId?: string;
  paneOrder: string[];
  conversations: readonly Conversation[];
  onClose: (id: string) => void;
  onPopout: (id: string) => void;
}) {
  const primaryDetach = usePaneHeaderDetach(() => {
    if (primaryId) onPopout(primaryId);
  });

  return (
    <div className="flex min-h-0 min-w-0 flex-1 overflow-x-auto" data-testid="conversation-panes">
      {paneOrder.map((id) =>
        id === primaryId ? (
          <section
            key={id}
            data-pane-id={id}
            className="relative flex min-h-0 min-w-0 flex-1 flex-col md:min-w-80"
            aria-label="Primary chat"
            style={{ "--workspace-panel-offset": "2.75rem" } as CSSProperties}
            {...primaryDetach.dragProps}
          >
            {primaryDetach.detachTarget}
            <div data-pane-drag-handle className="contents">
              {header}
            </div>
            {primary}
          </section>
        ) : (
          <ResizableChatPane
            key={id}
            label={`Chat: ${sessionLabel(conversations, id)}`}
            paneId={id}
            onPopout={() => onPopout(id)}
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
