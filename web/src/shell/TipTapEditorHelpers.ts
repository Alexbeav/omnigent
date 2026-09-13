// Text-content position helpers for TipTap / ProseMirror comment anchoring.
//
// Comments are anchored by (start_index, end_index) in the raw file and by
// anchor_content (the verbatim selected text).  These helpers bridge the gap
// between raw file offsets and ProseMirror integer positions.
//
// Strategy (both directions):
//   1. Build the PM text content with "\n" between blocks as a proxy for the
//      raw file content.
//   2. Use anchor_content as the primary match key; start_index as a ±500
//      window hint so duplicate text resolves to the right occurrence.
//   3. Map between text-content offset and PM position via binary search on
//      doc.textBetween(0, mid, "\n").length — O(log n · n) for typical docs.

import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import type { Comment } from "@/hooks/useComments";

const SEP = "\n";

/**
 * Returns the smallest PM position p where
 * doc.textBetween(0, p, SEP).length >= offset.
 *
 * Binary search over PM positions — O(log(doc.size) * doc.size).
 * Adequate for typical markdown documents (< 200 KB).
 */
function textOffsetToPmPos(doc: ProseMirrorNode, offset: number): number {
  const maxSize = doc.content.size;
  if (offset <= 0) return 0;
  const total = doc.textBetween(0, maxSize, SEP).length;
  if (offset >= total) return maxSize;
  let lo = 0;
  let hi = maxSize;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (doc.textBetween(0, mid, SEP).length < offset) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * Finds the PM [from, to) range for a saved comment.
 *
 * Uses anchor_content as the text to locate; start_index (a raw-file byte
 * offset) is scaled by the textContent/rawContent ratio to produce a hint
 * for where in the text content to search first.
 *
 * Returns null when anchor_content is absent or not found in the document.
 */
export function findPmRangeForComment(
  doc: ProseMirrorNode,
  comment: Comment,
  rawContent: string,
): { from: number; to: number } | null {
  const { anchor_content, start_index } = comment;
  if (!anchor_content?.trim()) return null;

  const textContent = doc.textBetween(0, doc.content.size, SEP);
  if (!textContent) return null;

  // Scale raw offset → text-content offset as a search hint.
  const hint =
    rawContent.length > 0 ? Math.round((start_index * textContent.length) / rawContent.length) : 0;

  const WINDOW = 500;
  const searchFrom = Math.max(0, hint - WINDOW);
  let textFrom = textContent.indexOf(anchor_content, searchFrom);
  if (textFrom === -1 || textFrom > hint + WINDOW) {
    textFrom = textContent.indexOf(anchor_content); // global fallback
  }
  if (textFrom === -1) return null;

  const from = textOffsetToPmPos(doc, textFrom);
  const to = textOffsetToPmPos(doc, textFrom + anchor_content.length);
  if (from >= to) return null;

  return { from, to };
}

// ---------------------------------------------------------------------------
// Markdown-syntax-tolerant anchor matching
// ---------------------------------------------------------------------------

// Inline markup markdown can interleave with rendered text within a line.
const INLINE_SKIP = "*_~`[]\\!<>";
// Markers that additionally open lines or separate blocks, list items, cells.
const GAP_SKIP = INLINE_SKIP + "#|-+:=";

// Same whitespace definition as the HTML comment bridge: code points <= U+0020.
const isWs = (ch: string) => ch.charCodeAt(0) <= 0x20;

// Code fence opener/closer with optional info string (skippable inside gaps).
const FENCE_RE = /(?:`{3,}|~{3,})[^\n]*/y;
// Ordered list marker such as "1." or "12)" followed by spacing.
const ORDERED_RE = /\d{1,9}[.)](?=[ \t])/y;

/** Skip a link/image tail at a "]" — "](url)" or "][ref]" — or just the "]". */
function skipBracketTail(raw: string, ri: number): number {
  if (raw[ri + 1] === "(") {
    let depth = 0;
    for (let i = ri + 1; i < raw.length && i <= ri + 1024; i++) {
      const c = raw[i];
      if (c === "\n") break; // link destinations don't span lines
      if (c === "(") depth++;
      else if (c === ")" && --depth === 0) return i + 1;
    }
  } else if (raw[ri + 1] === "[") {
    const close = raw.indexOf("]", ri + 2);
    if (close !== -1 && close - ri <= 1024) return close + 1;
  }
  return ri + 1;
}

/** Skip an image "![alt](url)" wholesale — its alt text is not rendered. */
function skipImage(raw: string, ri: number): number {
  const close = raw.indexOf("]", ri + 2);
  if (close !== -1 && close - ri <= 1024) return skipBracketTail(raw, close);
  return ri + 1;
}

/**
 * Matches `anchor[lead, tail)` (rendered text) against `raw` from `start`,
 * tolerating markdown syntax the renderer strips.  Content characters must
 * match exactly and in order — raw whitespace never substitutes for anchor
 * content, so words cannot fuse or split.  Whitespace gaps in the anchor
 * absorb any mix of whitespace and block/table/list markup in the raw text.
 * Returns the exclusive end offset of the matched span, or -1.
 */
function matchTolerant(
  raw: string,
  anchor: string,
  start: number,
  lead: number,
  tail: number,
): number {
  let ri = start;
  let ai = lead;
  while (ai < tail) {
    const ac = anchor[ai];
    if (isWs(ac)) {
      do ai++;
      while (ai < tail && isWs(anchor[ai]));
      const next = anchor[ai]; // tail ends at a content char, so this exists
      let consumed = 0;
      while (ri < raw.length) {
        const rc = raw[ri];
        if (isWs(rc)) {
          ri++;
          consumed++;
          continue;
        }
        if (rc === next && consumed > 0) break;
        FENCE_RE.lastIndex = ri;
        if (FENCE_RE.test(raw)) {
          consumed += FENCE_RE.lastIndex - ri;
          ri = FENCE_RE.lastIndex;
          continue;
        }
        ORDERED_RE.lastIndex = ri;
        if (ORDERED_RE.test(raw)) {
          consumed += ORDERED_RE.lastIndex - ri;
          ri = ORDERED_RE.lastIndex;
          continue;
        }
        if (rc === "!" && raw[ri + 1] === "[") {
          const n = skipImage(raw, ri);
          consumed += n - ri;
          ri = n;
          continue;
        }
        if (rc === "]") {
          const n = skipBracketTail(raw, ri);
          consumed += n - ri;
          ri = n;
          continue;
        }
        if (GAP_SKIP.includes(rc)) {
          ri++;
          consumed++;
          continue;
        }
        break;
      }
      if (consumed === 0) return -1;
      continue;
    }
    const rc = raw[ri];
    if (rc === undefined) return -1;
    if (rc === ac) {
      ri++;
      ai++;
      continue;
    }
    if (rc === "!" && raw[ri + 1] === "[") {
      ri = skipImage(raw, ri);
      continue;
    }
    if (rc === "]") {
      ri = skipBracketTail(raw, ri);
      continue;
    }
    if (INLINE_SKIP.includes(rc)) {
      ri++;
      continue;
    }
    return -1;
  }
  return ri;
}

/**
 * Finds the raw span whose rendered content equals `anchor`, preferring
 * candidates near `hint` (same ±window semantics as the verbatim search).
 * The span starts at the anchor's first content character and ends after its
 * last, so surrounding markdown syntax is never included.
 */
function findRawSpanTolerant(
  raw: string,
  anchor: string,
  hint: number,
  window: number,
): { start: number; end: number } | null {
  let lead = 0;
  while (lead < anchor.length && isWs(anchor[lead])) lead++;
  let tail = anchor.length;
  while (tail > lead && isWs(anchor[tail - 1])) tail--;
  if (lead >= tail) return null;
  const first = anchor[lead];

  const tryFrom = (from: number, until: number): { start: number; end: number } | null => {
    for (let idx = raw.indexOf(first, from); idx !== -1 && idx <= until;) {
      const end = matchTolerant(raw, anchor, idx, lead, tail);
      if (end !== -1) return { start: idx, end };
      idx = raw.indexOf(first, idx + 1);
    }
    return null;
  };

  return tryFrom(Math.max(0, hint - window), hint + window) ?? tryFrom(0, raw.length);
}

/**
 * Computes raw-file comment anchor data for a PM selection range.
 *
 * Extracts the selected text as anchor_content, then locates it in
 * rawContent: first verbatim (using the scaled text-content offset as a
 * hint), then tolerating the markdown syntax the renderer strips (inline
 * marks, link targets, list/table/heading markup, block separators).
 *
 * When the selection cannot be located at all, returns an empty placeholder
 * span (0, 0) — matching the HTML viewer convention — so the comment stays
 * available through anchor_content (the primary locator used by
 * findPmRangeForComment and by agents) instead of storing a guessed range
 * that points at unrelated text.
 *
 * Returns null only when the selection contains no text.
 */
export function computeSelectionData(
  from: number,
  to: number,
  doc: ProseMirrorNode,
  rawContent: string,
): { start_index: number; end_index: number; anchor_content: string } | null {
  const anchor_content = doc.textBetween(from, to, SEP);
  if (!anchor_content.trim()) return null;

  const textContent = doc.textBetween(0, doc.content.size, SEP);
  const textFrom = doc.textBetween(0, from, SEP).length;

  const hint =
    textContent.length > 0 ? Math.round((textFrom * rawContent.length) / textContent.length) : 0;

  const WINDOW = 500;
  const searchFrom = Math.max(0, hint - WINDOW);
  let idx = rawContent.indexOf(anchor_content, searchFrom);
  if (idx === -1 || idx > hint + WINDOW) {
    idx = rawContent.indexOf(anchor_content);
  }
  if (idx !== -1) {
    return {
      start_index: idx,
      end_index: idx + anchor_content.length,
      anchor_content,
    };
  }

  const span = findRawSpanTolerant(rawContent, anchor_content, hint, WINDOW);
  if (span) {
    return { start_index: span.start, end_index: span.end, anchor_content };
  }

  return { start_index: 0, end_index: 0, anchor_content };
}
