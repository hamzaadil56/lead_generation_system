// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { RunsList, isInFlight } from "@/components/runs-list";
import type { RunOut } from "@/lib/types";

// RunsList calls useRouter() to poll via router.refresh() while a run is in
// flight (see below). Outside a mounted Next.js app router, useRouter throws
// ("invariant expected app router to be mounted"), so every render() in this
// file needs the hook mocked -- matching the pattern already used for
// components/leads-table.test.tsx.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));

const run = (o: Partial<RunOut> = {}): RunOut => ({
  id: 1, status: "complete", source: "ui",
  search_plan: { vertical: "hvac", state: "tx", pages: 5 },
  stats: null, max_cost_usd: 5, estimated_cost: 0.012, actual_cost: 0.05,
  created_at: "2026-09-01T10:00:00Z", started_at: "2026-09-01T10:00:05Z",
  finished_at: "2026-09-01T10:04:00Z", error: null, ...o,
});

it("shows each run's status", () => {
  render(<RunsList rows={[run({ status: "running" })]} />);
  expect(screen.getByText(/running/i)).toBeInTheDocument();
});

it("shows a failed run's reason", () => {
  render(<RunsList rows={[run({ status: "failed", error: "budget: spent $6.00 of $5.00" })]} />);
  expect(screen.getByText(/spent \$6\.00/)).toBeInTheDocument();
});

it("does not present the estimate as comparable to the actual", () => {
  render(<RunsList rows={[run()]} />);
  // The estimate covers search only; labelling it plainly "estimated" beside
  // "actual" would read as a 4x overrun that never happened.
  expect(screen.getByText(/search est/i)).toBeInTheDocument();
});

it("renders an empty state when there are no runs", () => {
  render(<RunsList rows={[]} />);
  expect(screen.getByText(/no runs yet/i)).toBeInTheDocument();
});

it("isInFlight is true while anything is queued or running", () => {
  expect(isInFlight([run({ status: "queued" })])).toBe(true);
  expect(isInFlight([run({ status: "running" })])).toBe(true);
});

it("isInFlight is false once everything has settled", () => {
  expect(isInFlight([run({ status: "complete" }), run({ status: "failed" })])).toBe(false);
  expect(isInFlight([])).toBe(false);
});
