import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { buildPanePopoutUrl, normalizePaneIds } from "./ConversationPanes";

vi.mock("@/components/chat/SideChatPane", () => ({
  SideChatPane: ({ childId }: { childId: string }) => <div>pane:{childId}</div>,
}));

describe("conversation panes", () => {
  it("keeps at most two unique secondary sessions", () => {
    expect(normalizePaneIds("a", "b,b,a,c,d")).toEqual(["b", "c"]);
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

  it("provides an accessible add-pane fallback", async () => {
    const { ConversationPanes } = await import("./ConversationPanes");
    const onAdd = vi.fn();
    render(
      <ConversationPanes
        primary={<div>primary</div>}
        primaryId="a"
        paneIds={[]}
        conversations={
          [
            { id: "a", title: "First" },
            { id: "b", title: "Second" },
          ] as never
        }
        onAdd={onAdd}
        onClose={vi.fn()}
        onPopout={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Add chat pane"), { target: { value: "b" } });
    expect(onAdd).toHaveBeenCalledWith("b");
  });

  it("resizes a secondary pane with the keyboard", async () => {
    const { ConversationPanes } = await import("./ConversationPanes");
    render(
      <ConversationPanes
        primary={<div>primary</div>}
        primaryId="a"
        paneIds={["b"]}
        conversations={[{ id: "b", title: "Second" }] as never}
        onAdd={vi.fn()}
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
});
