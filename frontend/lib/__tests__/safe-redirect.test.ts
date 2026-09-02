import { expect, it } from "vitest";
import { safeNextPath } from "@/lib/safe-redirect";

it("keeps a legitimate same-origin path", () => {
  expect(safeNextPath("/runs/new")).toBe("/runs/new");
});

it("falls back to /leads when next is missing", () => {
  expect(safeNextPath(undefined)).toBe("/leads");
});

it("falls back to /leads for an absolute URL", () => {
  expect(safeNextPath("https://evil.example")).toBe("/leads");
});

it("falls back to /leads for a protocol-relative URL", () => {
  expect(safeNextPath("//evil.example")).toBe("/leads");
});

it("falls back to /leads for a javascript: URL", () => {
  expect(safeNextPath("javascript:alert(1)")).toBe("/leads");
});
