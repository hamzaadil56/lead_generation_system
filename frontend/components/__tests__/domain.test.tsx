// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { CoverageIndicator } from "@/components/coverage-indicator";
import { EvidenceQuote } from "@/components/evidence-quote";
import { QuadrantBadge } from "@/components/quadrant-badge";
import { ScorePair } from "@/components/score-pair";
import { SignalBadge } from "@/components/signal-badge";

it("ScorePair always shows both numbers, labelled", () => {
  render(<ScorePair fit={82} pain={41} />);
  expect(screen.getByText("82")).toBeInTheDocument();
  expect(screen.getByText("41")).toBeInTheDocument();
  expect(screen.getByLabelText(/fit 82, pain 41/i)).toBeInTheDocument();
});

// A real `cold` lead can score 0 on either axis, so 0 is a value the
// component must render, not a falsy blank. Mutating score-pair.tsx to
// `{fit || null}` -- dropping the number entirely -- used to leave the
// whole suite green, because every fixture in it scored non-zero.
it.each([
  [0, 0], [0, 41], [82, 0],
])("ScorePair renders a zero score as 0, not as blank (fit=%i pain=%i)",
   (fit, pain) => {
  const { container } = render(<ScorePair fit={fit} pain={pain} />);
  expect(container.textContent).toBe(`${fit}/${pain}`);
  expect(screen.getByLabelText(`Fit ${fit}, pain ${pain}`)).toBeInTheDocument();
});

it.each([
  ["go_now", "Go now"], ["nurture", "Nurture"],
  ["low_fit", "Low fit"], ["cold", "Cold"],
])("QuadrantBadge renders %s as %s", (q, label) => {
  render(<QuadrantBadge quadrant={q} />);
  expect(screen.getByText(label)).toBeInTheDocument();
});

it("QuadrantBadge gives each quadrant a distinct class", () => {
  const { container: a } = render(<QuadrantBadge quadrant="go_now" />);
  const { container: b } = render(<QuadrantBadge quadrant="cold" />);
  expect(a.firstElementChild?.className).not.toBe(b.firstElementChild?.className);
});

it("CoverageIndicator warns below the threshold and not above it", () => {
  const { unmount } = render(<CoverageIndicator coverage={0.4} />);
  expect(screen.getByRole("img", { name: /low coverage/i })).toBeInTheDocument();
  unmount();
  render(<CoverageIndicator coverage={0.9} />);
  expect(screen.queryByRole("img", { name: /low coverage/i })).toBeNull();
});

it("CoverageIndicator shows the value as a percentage", () => {
  render(<CoverageIndicator coverage={0.72} />);
  expect(screen.getByText("72%")).toBeInTheDocument();
});

it("EvidenceQuote shows the text verbatim", () => {
  render(<EvidenceQuote text="nobody ever answers the phone"
                        rating={1} publishedAt="2026-08-01T00:00:00Z" />);
  expect(screen.getByText(/nobody ever answers the phone/)).toBeInTheDocument();
});

it("SignalBadge renders a null signal as unknown, never as false", () => {
  render(<SignalBadge name="runs_google_ads" value={null} />);
  expect(screen.getByText(/unknown/i)).toBeInTheDocument();
  expect(screen.queryByText(/^no$/i)).toBeNull();
});

it("SignalBadge distinguishes a real false from an unknown", () => {
  render(<SignalBadge name="has_chat_widget" value={false} />);
  expect(screen.getByText(/^no$/i)).toBeInTheDocument();
  expect(screen.queryByText(/unknown/i)).toBeNull();
});
