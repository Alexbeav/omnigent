import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatComposer } from "@/components/composer/ChatComposer";
import { createInitialConversationState } from "@/store/conversationState";
import { authenticatedFetch } from "@/lib/identity";
import { writeReplySuggestionsEnabled } from "@/lib/replySuggestionsPreferences";
import { hasOutstandingAsyncQuestion, useReplySuggestion } from "./useReplySuggestion";

vi.mock("@/lib/identity", () => ({
  authenticatedFetch: vi.fn(),
  getCurrentUserId: () => "test-account",
}));
let session = 0;
function Editor({
  id,
  finished = false,
  active = true,
  writable = true,
  hasFiles = false,
  pending = false,
  harness = "codex-native",
  asyncQuestion = false,
}: {
  id: string;
  finished?: boolean;
  active?: boolean;
  writable?: boolean;
  hasFiles?: boolean;
  pending?: boolean;
  harness?: string;
  asyncQuestion?: boolean;
}) {
  const [text, setText] = useState("");
  const [surface, setSurface] = useState<HTMLDivElement | null>(null);
  const state = {
    ...createInitialConversationState(),
    sessionHarness: harness,
    replySuggestionTurn: finished ? "turn-1" : null,
    activeResponse: {
      responseId: "turn-1",
      state: finished ? ("completed" as const) : ("streaming" as const),
      error: null,
    },
    blockedOn: pending ? "question" : null,
  };
  if (asyncQuestion) {
    const question = {
      type: "text_done" as const,
      fullText: "Proceed?",
      hasCodeBlocks: false,
      ctx: {
        agent: null,
        depth: 0,
        turn: 0,
        timestamp: 0,
        responseId: "turn-1",
        itemId: "question-1",
      },
      asyncUserInput: {
        call_id: "call-1",
        reply_id: "reply-1",
        questions: [{ title: "Proceed?" }],
      },
    };
    state.blocks = [question];
  }
  const reply = useReplySuggestion({
    sessionId: id,
    state,
    empty: text === "" && !hasFiles,
    writable,
    active,
    surface,
  });
  return (
    <ChatComposer
      ref={setSurface}
      keyboard={{ submitWithModEnter: false, preventsKeyboardSubmit: false }}
      suggestion={reply.suggestion}
      onSuggestionHandled={reply.dismiss}
      input={{
        "aria-label": id,
        value: text,
        onChange: (event) => setText(event.target.value),
        placeholder: "Write here",
      }}
      actions={{ leading: null, trailing: null }}
    />
  );
}
async function tick() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(800);
  });
}
beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
  vi.mocked(authenticatedFetch)
    .mockReset()
    .mockResolvedValue(new Response(JSON.stringify({ status: "ready", text: "Show the diff." })));
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
    { width: 500, height: 100 },
  ] as unknown as DOMRectList);
  writeReplySuggestionsEnabled(true);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("reply suggestions", () => {
  it("runs on LAN HTTP without crypto.randomUUID", async () => {
    vi.stubGlobal("crypto", { getRandomValues: crypto.getRandomValues.bind(crypto) });
    const id = `session-${++session}`;
    const view = render(<Editor id={id} />);
    view.rerender(<Editor id={id} finished />);
    await tick();
    expect(authenticatedFetch).toHaveBeenCalledTimes(1);
    const body = JSON.parse(vi.mocked(authenticatedFetch).mock.calls[0]![1]!.body as string);
    expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
  });
  it("skips an outstanding async question until a correlated reply exists", () => {
    const question = {
      type: "text_done",
      ctx: { itemId: "question-1" },
      asyncUserInput: { call_id: "ask-1", reply_id: "reply-1", questions: [{ title: "Proceed?" }] },
    };
    expect(hasOutstandingAsyncQuestion([question])).toBe(true);
    expect(
      hasOutstandingAsyncQuestion([
        question,
        {
          type: "user_message",
          ctx: { itemId: "answer-1" },
          asyncQuestionReply: { source_item_id: "other-question", answers: {} },
        },
      ]),
    ).toBe(true);
    expect(
      hasOutstandingAsyncQuestion([
        question,
        {
          type: "user_message",
          ctx: { itemId: "answer-1" },
          asyncQuestionReply: { source_item_id: "question-1", answers: {}, cancelled: false },
        },
      ]),
    ).toBe(false);
  });

  it.each(["codex-native", "claude-native"])(
    "keeps %s suggestions out of drafts until accepted, and persists dismissal",
    async (harness) => {
      const id = `session-${++session}`;
      const view = render(<Editor id={id} harness={harness} />);
      view.rerender(<Editor id={id} harness={harness} finished />);
      await tick();
      const input = screen.getByLabelText(id);
      expect(input).toHaveValue("");
      expect(input).toHaveAttribute("placeholder", "Show the diff.");
      expect(authenticatedFetch).toHaveBeenCalledTimes(1);
      fireEvent.keyDown(input, { key: "Tab" });
      expect(input).toHaveValue("Show the diff.");
      fireEvent.change(input, { target: { value: "" } });
      view.unmount();
      render(<Editor id={id} harness={harness} finished />);
      await tick();
      expect(screen.getByLabelText(id)).toHaveAttribute("placeholder", "Write here");
      expect(authenticatedFetch).toHaveBeenCalledTimes(1);
    },
  );
  it.each([
    { active: false },
    { writable: false },
    { hasFiles: true },
    { pending: true },
    { asyncQuestion: true },
    { harness: "acp" },
  ])("does not generate for an ineligible completed turn: %j", async (props) => {
    render(<Editor id={`session-${++session}`} finished {...props} />);
    await tick();
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });
  it("does not generate when disabled or before a live completion", async () => {
    const id = `session-${++session}`;
    const view = render(<Editor id={id} />);
    await tick();
    expect(authenticatedFetch).not.toHaveBeenCalled();
    act(() => writeReplySuggestionsEnabled(false));
    view.rerender(<Editor id={id} finished />);
    await tick();
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });
  it("cancels and discards a late result when the user types", async () => {
    let resolve!: (response: Response) => void;
    vi.mocked(authenticatedFetch).mockImplementation((_url, init) =>
      init?.method === "DELETE"
        ? Promise.resolve(new Response("{}"))
        : new Promise<Response>((done) => {
            resolve = done;
          }),
    );
    const id = `session-${++session}`;
    const view = render(<Editor id={id} />);
    view.rerender(<Editor id={id} finished />);
    await tick();
    fireEvent.change(screen.getByLabelText(id), { target: { value: "Keep my draft" } });
    await act(async () =>
      resolve(new Response(JSON.stringify({ status: "ready", text: "Wrong late text" }))),
    );
    expect(screen.getByLabelText(id)).toHaveValue("Keep my draft");
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining("/next-reply/"),
      expect.objectContaining({ method: "DELETE" }),
    );
    fireEvent.change(screen.getByLabelText(id), { target: { value: "" } });
    expect(screen.getByLabelText(id)).toHaveAttribute("placeholder", "Write here");
  });
  it("cancels an in-flight result on document visibility loss", async () => {
    vi.mocked(authenticatedFetch).mockImplementation((_url, init) =>
      init?.method === "DELETE" ? Promise.resolve(new Response("{}")) : new Promise(() => {}),
    );
    const id = `session-${++session}`;
    const view = render(<Editor id={id} />);
    view.rerender(<Editor id={id} finished />);
    await tick();
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    fireEvent(document, new Event("visibilitychange"));
    expect(authenticatedFetch).toHaveBeenCalledWith(
      expect.stringContaining("/next-reply/"),
      expect.objectContaining({ method: "DELETE" }),
    );
  });
});
