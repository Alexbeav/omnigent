import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from "react";
import type { ConversationState } from "@/store/chatStore";
import { authenticatedFetch } from "@/lib/identity";
import { useReplySuggestionsEnabled } from "@/lib/replySuggestionsPreferences";
import { randomUUID } from "@/lib/randomUUID";

export function hasOutstandingAsyncQuestion(
  blocks: readonly {
    type: string;
    ctx: { itemId?: string | null };
    asyncUserInput?: unknown;
    asyncQuestionReply?: unknown;
  }[],
): boolean {
  // Older servers omit these fields. Replies resolve their source item, not a turn.
  const answered = new Set<string>();
  for (const block of blocks) {
    const reply = block.asyncQuestionReply;
    if (
      block.type === "user_message" &&
      reply &&
      typeof reply === "object" &&
      "source_item_id" in reply &&
      typeof reply.source_item_id === "string"
    ) {
      answered.add(reply.source_item_id);
    }
  }
  return blocks.some(
    (block) =>
      block.type === "text_done" &&
      block.asyncUserInput != null &&
      (!block.ctx.itemId || !answered.has(block.ctx.itemId)),
  );
}

interface Suggestion {
  id: string;
  text: string;
}
interface Entry {
  suggestion: Suggestion | null;
  cancel?: () => void;
  handled: boolean;
}
// One bounded cache shared by full chat and panes. No draft text is stored here.
const entries = new Map<string, Entry>();
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());
const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

export function useReplySuggestion({
  sessionId,
  state,
  empty,
  writable,
  active = true,
  surface,
}: {
  sessionId: string | null;
  state: ConversationState;
  empty: boolean;
  writable: boolean;
  active?: boolean;
  surface: HTMLElement | null;
}) {
  const enabled = useReplySuggestionsEnabled();
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const check = () =>
      setVisible(
        document.visibilityState !== "hidden" &&
          document.hasFocus() &&
          surface !== null &&
          surface.getClientRects().length > 0,
      );
    check();
    const observer = new ResizeObserver(check);
    if (surface) observer.observe(surface);
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    window.addEventListener("blur", check);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
      window.removeEventListener("blur", check);
    };
  }, [surface]);

  const turn = state.replySuggestionTurn;
  const key =
    sessionId && turn
      ? `${sessionId}:${turn}:${state.sessionModelOverride ?? ""}:${state.historyGeneration}`
      : null;
  const eligible =
    !!key &&
    enabled &&
    active &&
    visible &&
    writable &&
    empty &&
    (state.sessionHarness === "codex-native" || state.sessionHarness === "claude-native") &&
    state.sessionStatus === "idle" &&
    state.status !== "streaming" &&
    state.activeResponse?.state === "completed" &&
    state.activeResponse.responseId === turn &&
    state.pendingUserMessages.length === 0 &&
    state.backgroundTaskCount === 0 &&
    state.blockedOn === null &&
    !hasOutstandingAsyncQuestion(state.blocks) &&
    !state.blocks.some(
      (block) =>
        (block.type === "elicitation" && block.status === "pending") ||
        block.type === "compaction_loading",
    );
  const current = useRef({ key, eligible });
  useLayoutEffect(() => {
    current.current = { key, eligible };
  });
  const suggestion = useSyncExternalStore(
    subscribe,
    () => (key ? (entries.get(key)?.suggestion ?? null) : null),
    () => null,
  );
  const dismiss = () => {
    if (!key) return;
    const entry = entries.get(key);
    entry?.cancel?.();
    entries.set(key, { handled: true, suggestion: null });
    notify();
  };

  useEffect(() => {
    if (!key || !sessionId) return;
    const cached = entries.get(key);
    if (cached) {
      if ((!empty || !writable || !enabled) && !cached.handled) {
        cached.cancel?.();
        entries.set(key, { handled: true, suggestion: null });
        notify();
      }
      return;
    }
    // A completion in an inactive/hidden composer spends no inference later on focus.
    const entry: Entry = { suggestion: null, handled: !eligible };
    entries.set(key, entry);
    if (entries.size > 128) entries.delete(entries.keys().next().value!);
    if (!eligible) return;
    const controller = new AbortController();
    const requestId = randomUUID();
    const url = `/v1/sessions/${encodeURIComponent(sessionId)}/next-reply`;
    let started = false;
    let finished = false;
    const timer = window.setTimeout(() => {
      if (!current.current.eligible || current.current.key !== key) return;
      started = true;
      void authenticatedFetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source_response_id: turn, request_id: requestId, enabled: true }),
        signal: controller.signal,
      })
        .then(async (response) => {
          if (!response.ok) return;
          const result = await response.json();
          if (
            controller.signal.aborted ||
            current.current.key !== key ||
            !current.current.eligible ||
            entry.handled ||
            entries.get(key) !== entry
          )
            return;
          if (
            result.status === "ready" &&
            typeof result.text === "string" &&
            result.text.trim() &&
            result.text.length <= 300
          ) {
            entry.suggestion = { id: key, text: result.text };
            notify();
          }
        })
        .catch(() => {
          /* Suggestions never block the composer. No retries. */
        })
        .finally(() => {
          finished = true;
          entry.cancel = undefined;
        });
    }, 750);
    const deadline = window.setTimeout(() => entry.cancel?.(), 20_000);
    entry.cancel = () => {
      window.clearTimeout(timer);
      window.clearTimeout(deadline);
      controller.abort();
      entry.handled = true;
      entry.suggestion = null;
      if (started && !finished)
        void authenticatedFetch(`${url}/${requestId}`, {
          method: "DELETE",
          keepalive: true,
        }).catch(() => {});
      entry.cancel = undefined;
      notify();
    };
    return () => {
      if (!finished) entry.cancel?.();
    };
  }, [key, sessionId, turn, eligible, empty, writable, enabled]);

  return { suggestion: eligible ? suggestion : null, dismiss };
}
