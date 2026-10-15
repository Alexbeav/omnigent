import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { buildPanePopoutUrl, normalizePaneIds, normalizePaneOrder } from "./ConversationPanes";
import { isChatDetachPoint } from "./chatDetach";

vi.mock("@/components/chat/SideChatPane", () => ({
  SideChatPane: ({ childId }: { childId: string }) => <div>pane:{childId}</div>,
}));

describe("conversation panes", () => {
  it("keeps at most two unique secondary sessions", () => {
    expect(normalizePaneIds("a", "b,b,a,c,d")).toEqual(["b", "c"]);
  });

  it("persists visual order without changing the primary identity", () => {
    expect(normalizePaneOrder("a", ["b", "c"], "b,a,c")).toEqual(["b", "a", "c"]);
    expect(normalizePaneOrder("a", ["b", "c"], "missing,c,c")).toEqual(["c", "a", "b"]);
  });

  it("renders a secondary on either side of the primary in the requested order", async () => {
    const { ConversationPanes } = await import("./ConversationPanes");
    const { container } = render(
      <ConversationPanes
        primary={<div>primary</div>}
        primaryId="a"
        paneOrder={["b", "a", "c"]}
        conversations={
          [
            { id: "b", title: "Second" },
            { id: "c", title: "Third" },
          ] as never
        }
        onClose={vi.fn()}
        onPopout={vi.fn()}
      />,
    );
    expect(
      Array.from(container.querySelectorAll("section[data-pane-id]"), (pane) =>
        pane.getAttribute("data-pane-id"),
      ),
    ).toEqual(["b", "a", "c"]);
  });

  it("recognizes only the outer detach edge and outside releases", () => {
    expect(isChatDetachPoint(951, 200, 1000, 800)).toBe(false);
    expect(isChatDetachPoint(952, 200, 1000, 800)).toBe(true);
    expect(isChatDetachPoint(1001, 200, 1000, 800)).toBe(true);
    expect(isChatDetachPoint(500, 200, 1000, 800)).toBe(false);
  });

  it("rebases popouts and retains unrelated query state", () => {
    const url = buildPanePopoutUrl(
      "https://example.test/mount/c/one?account=alex&panes=two,three&file=old.txt&panel=agents&view=terminal&message=old#old",
      "two/slash",
      (path) => `/mount${path}`,
    );
    expect(url.pathname).toBe("/mount/c/two%2Fslash");
    expect(url.search).toBe("?account=alex");
    expect(url.hash).toBe("");
  });

  it("resizes a secondary pane with the keyboard", async () => {
    const { ConversationPanes } = await import("./ConversationPanes");
    render(
      <ConversationPanes
        primary={<div>primary</div>}
        primaryId="a"
        paneOrder={["a", "b"]}
        conversations={[{ id: "b", title: "Second" }] as never}
        onClose={vi.fn()}
        onPopout={vi.fn()}
      />,
    );
    const separator = screen.getByRole("separator", { name: "Resize Chat: Second" });
    const pane = separator.parentElement!;
    Object.defineProperty(pane, "offsetWidth", { configurable: true, value: 420 });
    Object.defineProperty(pane.parentElement!, "clientWidth", { configurable: true, value: 900 });
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    expect(pane).toHaveStyle({ flex: "0 0 440px" });
    Object.defineProperty(pane, "offsetWidth", { configurable: true, value: 575 });
    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    expect(pane).toHaveStyle({ flex: "0 0 580px" });
  });

  it("pops out a pane only after its header reaches the detach edge", async () => {
    const { ConversationPanes } = await import("./ConversationPanes");
    const onPopout = vi.fn();
    render(
      <ConversationPanes
        primary={<div>primary</div>}
        primaryId="a"
        paneOrder={["a", "b"]}
        conversations={[{ id: "b", title: "Second" }] as never}
        onClose={vi.fn()}
        onPopout={onPopout}
      />,
    );
    const header = screen.getByText("Second").closest("header")!;
    const pane = header.closest("section")!;
    pane.setPointerCapture = vi.fn();
    fireEvent.pointerDown(header, { button: 0, pointerId: 1, clientX: 500, clientY: 20 });
    fireEvent.pointerMove(pane, { pointerId: 1, clientX: 600, clientY: 20 });
    expect(screen.getByTestId("chat-detach-target")).toBeInTheDocument();
    fireEvent.pointerUp(pane, { pointerId: 1, clientX: window.innerWidth - 1, clientY: 20 });
    expect(onPopout).toHaveBeenCalledExactlyOnceWith("b");

    fireEvent.pointerDown(header, { button: 0, pointerId: 2, clientX: 500, clientY: 20 });
    fireEvent.pointerCancel(pane, { pointerId: 2 });
    expect(onPopout).toHaveBeenCalledTimes(1);
  });

  it("shares cancellation and outside release behavior with the primary header", async () => {
    const { ConversationPanes } = await import("./ConversationPanes");
    const onPopout = vi.fn();
    render(
      <ConversationPanes
        primary={<div>primary</div>}
        header={<header>Primary title</header>}
        primaryId="a"
        paneOrder={["a"]}
        conversations={[]}
        onClose={vi.fn()}
        onPopout={onPopout}
      />,
    );
    const pane = screen.getByRole("region", { name: "Primary chat" });
    const header = screen.getByText("Primary title");
    pane.setPointerCapture = vi.fn();
    pane.hasPointerCapture = vi.fn(() => true);
    pane.releasePointerCapture = vi.fn();

    fireEvent.pointerDown(header, { button: 0, pointerId: 1, clientX: 500, clientY: 20 });
    fireEvent.pointerMove(pane, { pointerId: 1, clientX: 550, clientY: 20 });
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByTestId("chat-detach-target")).not.toBeInTheDocument();
    fireEvent.pointerUp(pane, { pointerId: 1, clientX: window.innerWidth + 1, clientY: 20 });
    expect(onPopout).not.toHaveBeenCalled();

    fireEvent.pointerDown(header, { button: 0, pointerId: 2, clientX: 500, clientY: 20 });
    fireEvent.pointerMove(pane, { pointerId: 2, clientX: 550, clientY: 20 });
    fireEvent.lostPointerCapture(pane, { pointerId: 2 });
    fireEvent.pointerUp(pane, { pointerId: 2, clientX: window.innerWidth + 1, clientY: 20 });
    expect(onPopout).not.toHaveBeenCalled();

    fireEvent.pointerDown(header, { button: 0, pointerId: 3, clientX: 500, clientY: 20 });
    fireEvent.pointerMove(pane, { pointerId: 3, clientX: 550, clientY: 20 });
    fireEvent.pointerUp(pane, { pointerId: 3, clientX: window.innerWidth + 1, clientY: 20 });
    expect(onPopout).toHaveBeenCalledExactlyOnceWith("a");
  });
});
