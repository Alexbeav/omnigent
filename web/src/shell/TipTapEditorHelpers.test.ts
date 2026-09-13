import { describe, expect, it } from "vitest";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { findPmRangeForComment, computeSelectionData } from "./TipTapEditorHelpers";
import type { Comment } from "@/hooks/useComments";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * Build a minimal ProseMirror Node mock where textBetween(from, to, sep)
 * is just text.slice(from, to).
 *
 * This collapses PM positions to text offsets (1:1 mapping), which makes
 * expected values trivial to compute while fully exercising the string
 * matching and binary search logic in the helpers.
 */
function makeDoc(text: string): ProseMirrorNode {
  return {
    content: { size: text.length },
    textBetween: (from: number, to: number, _sep: string) => text.slice(from, to),
  } as unknown as ProseMirrorNode;
}

/** Build a minimal Comment with only the fields the helpers use. */
function makeComment(
  anchor_content: string,
  start_index: number,
  end_index: number = start_index + anchor_content.length,
): Comment {
  return {
    id: "test-comment",
    start_index,
    end_index,
    anchor_content,
    body: "",
    created_at: "",
    author: null,
  } as unknown as Comment;
}

// ---------------------------------------------------------------------------
// findPmRangeForComment
// ---------------------------------------------------------------------------

describe("findPmRangeForComment", () => {
  const raw = "Hello, world! Hello, universe!";

  it("returns null when anchor_content is absent (undefined)", () => {
    const doc = makeDoc("Hello, world!");
    const comment = makeComment("x", 0);
    (comment as unknown as Record<string, unknown>).anchor_content = undefined;
    expect(findPmRangeForComment(doc, comment, raw)).toBeNull();
  });

  it("returns null when anchor_content is empty string", () => {
    const doc = makeDoc("Hello, world!");
    expect(findPmRangeForComment(doc, makeComment("", 0), raw)).toBeNull();
  });

  it("returns null when anchor_content is whitespace only", () => {
    const doc = makeDoc("Hello, world!");
    expect(findPmRangeForComment(doc, makeComment("   ", 0), raw)).toBeNull();
  });

  it("returns null when anchor_content is not present in the document", () => {
    const doc = makeDoc("Hello, world!");
    expect(findPmRangeForComment(doc, makeComment("missing text", 0), raw)).toBeNull();
  });

  it("finds anchor at the very beginning of the document", () => {
    const doc = makeDoc("Hello, world!");
    const result = findPmRangeForComment(doc, makeComment("Hello", 0), "Hello, world!");
    expect(result).toEqual({ from: 0, to: 5 });
  });

  it("finds anchor in the middle of the document", () => {
    const text = "Hello, world!";
    const doc = makeDoc(text);
    const result = findPmRangeForComment(doc, makeComment("world", 7), text);
    expect(result).toEqual({ from: 7, to: 12 });
  });

  it("finds anchor at the end of the document", () => {
    const text = "Hello, world!";
    const doc = makeDoc(text);
    const result = findPmRangeForComment(doc, makeComment("world!", 7), text);
    expect(result).toEqual({ from: 7, to: 13 });
  });

  it("uses start_index hint to skip the first occurrence when it is >500 chars away", () => {
    // "foo" appears at 0 and again at 600. With hint=600 the search window
    // starts at 100 (= 600-500), so indexOf("foo", 100) finds the second
    // occurrence at 600, not the first at 0.
    const prefix = "x".repeat(597);
    const text = "foo" + prefix + "foo"; // "foo" at 0 and 600
    const doc = makeDoc(text);
    const result = findPmRangeForComment(doc, makeComment("foo", 600), text);
    expect(result).toEqual({ from: 600, to: 603 });
  });

  it("returns the first occurrence when two identical strings are within the ±500 window", () => {
    // Both "Hello"s are within 500 chars of each other; searchFrom collapses
    // to 0 and indexOf returns the first match regardless of the hint.
    const text = "Hello, world! Hello, universe!";
    const doc = makeDoc(text);
    const result = findPmRangeForComment(doc, makeComment("Hello", 14), text);
    expect(result).toEqual({ from: 0, to: 5 });
  });

  it("falls back to the first occurrence when hint window misses", () => {
    // start_index=999 is way past the end; global fallback finds index 0.
    const text = "Hello, world!";
    const doc = makeDoc(text);
    const result = findPmRangeForComment(doc, makeComment("Hello", 999), text);
    expect(result).toEqual({ from: 0, to: 5 });
  });

  it("handles an empty document", () => {
    const doc = makeDoc("");
    expect(findPmRangeForComment(doc, makeComment("Hello", 0), "Hello")).toBeNull();
  });

  it("scales raw-file offset to text-content offset when rawContent is longer than text", () => {
    // Raw file has extra markdown syntax not in the doc text.
    // rawContent: "# Title\n\nHello, world!"  (len 22)
    // doc text:   "Title\nHello, world!"      (len 19)
    // anchor "Hello" at raw offset 10 → scaled hint ≈ 8 → finds at text offset 6.
    const rawContent = "# Title\n\nHello, world!";
    const docText = "Title\nHello, world!";
    const doc = makeDoc(docText);
    const result = findPmRangeForComment(doc, makeComment("Hello", 10), rawContent);
    expect(result).toEqual({ from: 6, to: 11 });
  });
});

// ---------------------------------------------------------------------------
// computeSelectionData
// ---------------------------------------------------------------------------

describe("computeSelectionData", () => {
  it("returns null when the selected PM range contains no text", () => {
    const text = "Hello, world!";
    const doc = makeDoc(text);
    expect(computeSelectionData(5, 5, doc, text)).toBeNull();
  });

  it("returns null when the selected text is whitespace only", () => {
    const text = "Hello   world";
    const doc = makeDoc(text);
    // Select the spaces at positions 5..8
    expect(computeSelectionData(5, 8, doc, text)).toBeNull();
  });

  it("returns correct indices when anchor is found verbatim in rawContent", () => {
    const text = "Hello, world!";
    const doc = makeDoc(text);
    const result = computeSelectionData(7, 12, doc, text);
    expect(result).toEqual({ start_index: 7, end_index: 12, anchor_content: "world" });
  });

  it("uses anchor_content as-is (no trimming)", () => {
    // Selection includes a trailing space — should be stored verbatim.
    const text = "Hello, world!";
    const doc = makeDoc(text);
    const result = computeSelectionData(0, 7, doc, text); // "Hello, "
    expect(result).toEqual({ start_index: 0, end_index: 7, anchor_content: "Hello, " });
  });

  it("skips the first occurrence when hint places it >500 chars away", () => {
    // "foo" at raw offset 0 and again at 600. Selection covers the second
    // "foo" (text offset 600); hint = 600, searchFrom = 100, so indexOf
    // returns the match at 600.
    const padding = "x".repeat(597);
    const text = "foo" + padding + "foo"; // "foo" at 0 and 600
    const doc = makeDoc(text);
    const result = computeSelectionData(600, 603, doc, text);
    expect(result).toEqual({ start_index: 600, end_index: 603, anchor_content: "foo" });
  });

  it("returns the first occurrence when duplicate strings are within the ±500 window", () => {
    // Both "foo"s are close together; the search window starts at 0 and
    // indexOf always finds the first match.
    const text = "foo bar foo baz";
    const doc = makeDoc(text);
    const result = computeSelectionData(8, 11, doc, text);
    expect(result).toEqual({ start_index: 0, end_index: 3, anchor_content: "foo" });
  });

  it("recovers the real raw span when line endings differ (\\n vs \\r\\n)", () => {
    const docText = "first\nsecond"; // doc joins blocks with "\n"
    const rawContent = "first\r\nsecond"; // raw file uses "\r\n"
    const doc = makeDoc(docText);
    const result = computeSelectionData(0, 12, doc, rawContent);
    expect(result).toEqual({
      start_index: 0,
      end_index: rawContent.length,
      anchor_content: "first\nsecond",
    });
  });

  it("stores an empty placeholder span when rawContent is empty", () => {
    const text = "Hello";
    const doc = makeDoc(text);
    const result = computeSelectionData(0, 5, doc, "");
    expect(result).toEqual({ start_index: 0, end_index: 0, anchor_content: "Hello" });
  });

  it("handles selection of the full document", () => {
    const text = "Hello, world!";
    const doc = makeDoc(text);
    const result = computeSelectionData(0, text.length, doc, text);
    expect(result).toEqual({
      start_index: 0,
      end_index: text.length,
      anchor_content: text,
    });
  });
});

// ---------------------------------------------------------------------------
// computeSelectionData — selections with no verbatim source match
// ---------------------------------------------------------------------------

describe("computeSelectionData with markdown syntax in the source", () => {
  it("stores the real raw span when the selection spans inline formatting", () => {
    const rawContent =
      "A plain paragraph with no formatting at all.\n\n" +
      "This paragraph has **formatted words** inside.\n";
    const docText =
      "A plain paragraph with no formatting at all.\n" +
      "This paragraph has formatted words inside.";
    const doc = makeDoc(docText);
    const selStart = docText.indexOf("This");
    const result = computeSelectionData(selStart, docText.length, doc, rawContent);
    expect(result!.anchor_content).toBe("This paragraph has formatted words inside.");
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe(
      "This paragraph has **formatted words** inside.",
    );
  });

  it("anchors a selection ending inside emphasized text at the right raw offsets", () => {
    const rawContent = "This paragraph has **formatted words** inside.";
    const docText = "This paragraph has formatted words inside.";
    const doc = makeDoc(docText);
    // Select "has formatted" — crosses into the strong mark.
    const from = docText.indexOf("has");
    const result = computeSelectionData(from, from + "has formatted".length, doc, rawContent);
    expect(result!.anchor_content).toBe("has formatted");
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe("has **formatted");
  });

  it("anchors intra-word emphasis selections", () => {
    const rawContent = "some intra**word**emphasis here";
    const docText = "some intrawordemphasis here";
    const doc = makeDoc(docText);
    const from = docText.indexOf("intra");
    const result = computeSelectionData(from, from + "intrawordemphasis".length, doc, rawContent);
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe("intra**word**emphasis");
  });

  it("anchors text selected across a markdown link, spanning the URL in raw", () => {
    const rawContent = "see [the docs](https://example.com) for more";
    const docText = "see the docs for more";
    const doc = makeDoc(docText);
    const from = docText.indexOf("the");
    const result = computeSelectionData(from, docText.length, doc, rawContent);
    expect(result!.anchor_content).toBe("the docs for more");
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe(
      "the docs](https://example.com) for more",
    );
  });

  it("anchors a selection spanning list items past the bullet markers", () => {
    const rawContent = "- item one\n- item two\n";
    const docText = "item one\nitem two";
    const doc = makeDoc(docText);
    const result = computeSelectionData(0, docText.length, doc, rawContent);
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe("item one\n- item two");
  });

  it("anchors a selection spanning ordered list items past the numeric markers", () => {
    const rawContent = "1. first step\n2. second step\n";
    const docText = "first step\nsecond step";
    const doc = makeDoc(docText);
    const result = computeSelectionData(0, docText.length, doc, rawContent);
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe(
      "first step\n2. second step",
    );
  });

  it("anchors a selection spanning table cells across pipes and the alignment row", () => {
    const rawContent = "| alpha | beta |\n| --- | --- |\n| one | two |\n";
    const docText = "alpha\nbeta\none\ntwo";
    const doc = makeDoc(docText);
    const from = docText.indexOf("beta");
    const result = computeSelectionData(from, docText.indexOf("two") + 3, doc, rawContent);
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe(
      "beta |\n| --- | --- |\n| one | two",
    );
  });

  it("anchors a heading-to-body selection past the heading markers", () => {
    const rawContent = "## Title\n\nBody text\n";
    const docText = "Title\nBody text";
    const doc = makeDoc(docText);
    const result = computeSelectionData(0, docText.length, doc, rawContent);
    expect(rawContent.slice(result!.start_index, result!.end_index)).toBe("Title\n\nBody text");
  });

  it("never fuses words: raw whitespace does not stand in for anchor content", () => {
    // "ab" must not silently anchor to "a b" — that would select wrong text.
    const doc = makeDoc("ab");
    const result = computeSelectionData(0, 2, doc, "a b");
    expect(result).toEqual({ start_index: 0, end_index: 0, anchor_content: "ab" });
  });

  it("stores an empty placeholder span when the selection cannot be located at all", () => {
    const doc = makeDoc("completely different words");
    const result = computeSelectionData(0, 10, doc, "# Unrelated raw content\n");
    expect(result).toEqual({ start_index: 0, end_index: 0, anchor_content: "completely" });
  });
});
