// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { LeadsTable } from "@/components/leads-table";
import type { LeadOut } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/leads",
}));

const lead = (over: Partial<LeadOut> = {}): LeadOut => ({
  cid: "c1", name: "Air Tech", city: "Houston", state: "TX",
  website: "https://example.com", phone: "+17135551234",
  segment: "growth", review_count: 300,
  fit_score: 80, pain_score: 70, quadrant: "go_now",
  coverage: 0.8, outcome_status: null, ...over,
});

it("renders both scores for every row", () => {
  render(<LeadsTable rows={[lead()]} />);
  expect(screen.getByLabelText(/fit 80, pain 70/i)).toBeInTheDocument();
});

it("shows a dash rather than a phone number when the API suppressed it", () => {
  render(<LeadsTable rows={[lead({ phone: null })]} />);
  expect(screen.queryByText(/\+1713/)).toBeNull();
});

it("has no column that sorts by review count", () => {
  render(<LeadsTable rows={[lead()]} />);
  // ADR-022: ratingCount is a label, never a control.
  expect(screen.queryByRole("button", { name: /review count/i })).toBeNull();
});

it("links each row to its detail page by cid", () => {
  render(<LeadsTable rows={[lead({ cid: "abc123" })]} />);
  expect(screen.getByRole("link", { name: /air tech/i }))
    .toHaveAttribute("href", "/leads/abc123");
});

it("renders an empty state rather than a bare table when there are no rows", () => {
  render(<LeadsTable rows={[]} />);
  expect(screen.getByText(/no leads match/i)).toBeInTheDocument();
});

it("shows the coverage warning on a low-coverage lead", () => {
  render(<LeadsTable rows={[lead({ coverage: 0.3 })]} />);
  expect(screen.getByRole("img", { name: /low coverage/i })).toBeInTheDocument();
});
