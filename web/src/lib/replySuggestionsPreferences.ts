import { useSyncExternalStore } from "react";
import { getCurrentUserId } from "./identity";

const CHANGE_EVENT = "omnigent:reply-suggestions-change";
export function replySuggestionsStorageKey(): string {
  return `omnigent:reply-suggestions:${getCurrentUserId() ?? "local"}`;
}
export function readReplySuggestionsEnabled(): boolean {
  try {
    return localStorage.getItem(replySuggestionsStorageKey()) === "on";
  } catch {
    return false;
  }
}
export function writeReplySuggestionsEnabled(enabled: boolean): void {
  try {
    localStorage.setItem(replySuggestionsStorageKey(), enabled ? "on" : "off");
  } catch {
    // A blocked preference never enables background inference.
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}
function subscribe(listener: () => void) {
  window.addEventListener(CHANGE_EVENT, listener);
  window.addEventListener("storage", listener);
  return () => {
    window.removeEventListener(CHANGE_EVENT, listener);
    window.removeEventListener("storage", listener);
  };
}
export function useReplySuggestionsEnabled(): boolean {
  return useSyncExternalStore(subscribe, readReplySuggestionsEnabled, () => false);
}
