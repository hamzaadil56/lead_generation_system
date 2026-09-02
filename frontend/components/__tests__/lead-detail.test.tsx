// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ReasonList, SignalList } from "@/components/lead-forms";
import type { ReasonOut } from "@/lib/types";

const reason = (o: Partial<ReasonOut> = {}): ReasonOut => ({
  rule: "uses_fsm", track: "fit", matched: true, points: 30,
  label: "Uses field service software", evidence: null, ...o,
});

it("separates fit reasons from pain reasons", () => {
  render(<ReasonList reasons={[
    reason(), reason({ rule: "closes_early", track: "pain", label: "Closes before 6pm" }),
  ]} />);
  expect(screen.getByText(/uses field service software/i)).toBeInTheDocument();
  expect(screen.getByText(/closes before 6pm/i)).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /fit/i })).toBeInTheDocument();
  expect(screen.getByRole("heading", { name: /pain/i })).toBeInTheDocument();
});

it("shows unmatched rules differently from matched ones", () => {
  render(<ReasonList reasons={[
    reason({ rule: "a", label: "Matched rule", matched: true }),
    reason({ rule: "b", label: "Unmatched rule", matched: false }),
  ]} />);
  // Word-boundary anchors: a plain /matched rule/i also matches the tail of
  // "Unmatched rule" as a substring, which would make this ambiguous.
  const matched = screen.getByText(/\bmatched rule\b/i).closest("li");
  const unmatched = screen.getByText(/\bunmatched rule\b/i).closest("li");
  expect(matched?.className).not.toBe(unmatched?.className);
});

it("shows a matched rule's points", () => {
  render(<ReasonList reasons={[reason({ points: 30, matched: true })]} />);
  expect(screen.getByText(/30/)).toBeInTheDocument();
});

it("renders a rule's evidence when present", () => {
  render(<ReasonList reasons={[reason({ evidence: ["nobody answers"] })]} />);
  expect(screen.getByText(/nobody answers/)).toBeInTheDocument();
});

// The label and value render as separate <span> children of the badge, so
// their combined text is split across elements — match on the badge's full
// textContent rather than a single text node (RTL's own suggested fix).
const badgeText = (text: string) => (_: string, node: Element | null) =>
  node?.textContent?.toLowerCase() === text.toLowerCase();

it("SignalList renders a null signal as unknown", () => {
  render(<SignalList signals={{ runs_google_ads: null, has_chat_widget: false }} />);
  expect(screen.getByText(badgeText("Runs google ads: unknown"))).toBeInTheDocument();
  expect(screen.getByText(badgeText("Has chat widget: no"))).toBeInTheDocument();
});
