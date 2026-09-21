import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as ChatStoreModule from "@/store/chatStore";

import { TooltipProvider } from "@/components/ui/tooltip";
import { useChatStore } from "@/store/chatStore";
import { PermissionModeBadge } from "./PermissionModeBadge";

const { setClaudePermissionModeMock } = vi.hoisted(() => ({
  setClaudePermissionModeMock: vi.fn(() => Promise.resolve()),
}));

// The badge only reads and writes two store members; stub the writer so a
// click is observable without a server round-trip.
vi.mock("@/store/chatStore", async (importOriginal) => {
  const actual = await importOriginal<typeof ChatStoreModule>();
  return {
    ...actual,
    useChatStore: Object.assign(
      (selector: (state: unknown) => unknown) =>
        selector({
          ...actual.useChatStore.getState(),
          setClaudePermissionMode: setClaudePermissionModeMock,
        }),
      {
        getState: () => ({
          ...actual.useChatStore.getState(),
          setClaudePermissionMode: setClaudePermissionModeMock,
        }),
        setState: actual.useChatStore.setState,
        subscribe: actual.useChatStore.subscribe,
      },
    ),
  };
});

afterEach(() => {
  cleanup();
  setClaudePermissionModeMock.mockClear();
  useChatStore.setState({ claudePermissionMode: "" });
});

function renderBadge() {
  return render(
    <TooltipProvider>
      <PermissionModeBadge />
    </TooltipProvider>,
  );
}

describe("PermissionModeBadge", () => {
  it("renders nothing while the mode is unknown", () => {
    // "" is the store's unknown mode. A claude-native session whose settings
    // file sets `permissions.defaultMode` reports no mode here, and guessing
    // would show a mode the session is not in.
    useChatStore.setState({ claudePermissionMode: "" });
    renderBadge();
    expect(screen.queryByTestId("header-permission-mode")).toBeNull();
  });

  it("shows the current mode's human label", () => {
    useChatStore.setState({ claudePermissionMode: "acceptEdits" });
    renderBadge();
    const badge = screen.getByTestId("header-permission-mode");
    expect(badge.textContent).toBe("Accept edits");
    expect(badge.getAttribute("data-permission-mode")).toBe("acceptEdits");
  });

  it("labels the prompting mode Manual, matching Claude's own UI", () => {
    useChatStore.setState({ claudePermissionMode: "default" });
    renderBadge();
    expect(screen.getByTestId("header-permission-mode").textContent).toBe("Manual");
  });

  it("flags a mode that runs without prompting", () => {
    // Bypass and Don't ask carry a warning tone so an unguarded session is
    // distinguishable at a glance from one that still asks.
    useChatStore.setState({ claudePermissionMode: "bypassPermissions" });
    renderBadge();
    expect(screen.getByTestId("header-permission-mode").className).toContain("amber");
  });

  it("writes the picked mode through to the store", async () => {
    useChatStore.setState({ claudePermissionMode: "default" });
    renderBadge();
    // Radix opens the menu on pointerdown, not click.
    fireEvent.pointerDown(
      screen.getByTestId("header-permission-mode"),
      new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0 }),
    );
    const option = await screen.findByTestId(
      "permission-mode-option-acceptEdits",
      {},
      { timeout: 3000 },
    );
    fireEvent.click(option);
    await waitFor(() => expect(setClaudePermissionModeMock).toHaveBeenCalledWith("acceptEdits"));
  });

  it("leaves the current mode selectable but inert", async () => {
    // The active mode stays in the list so the trigger and the open menu
    // agree; it must not re-issue a write for the mode already in force.
    useChatStore.setState({ claudePermissionMode: "plan" });
    renderBadge();
    fireEvent.pointerDown(
      screen.getByTestId("header-permission-mode"),
      new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0 }),
    );
    const current = await screen.findByTestId("permission-mode-option-plan", {}, { timeout: 3000 });
    expect(current.getAttribute("data-disabled")).not.toBeNull();
  });
});
