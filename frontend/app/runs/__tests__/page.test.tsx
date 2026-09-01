// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Page, RunOut } from "@/lib/types";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const apiGetMock = vi.fn();
class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({ apiGet: apiGetMock, ApiError: MockApiError }));

const { default: RunsPage } = await import("@/app/runs/page");

const run = (id: number): RunOut => ({
  id, status: "complete", source: "ui",
  search_plan: { vertical: "hvac", state: "tx", pages: 5 },
  stats: null, max_cost_usd: 5, estimated_cost: 0.012, actual_cost: 0.05,
  created_at: "2026-09-01T10:00:00Z", started_at: "2026-09-01T10:00:05Z",
  finished_at: "2026-09-01T10:04:00Z", error: null,
});

const page = (over: Partial<Page<RunOut>> = {}): Page<RunOut> => ({
  items: [run(1)], total: 120, page: 1, page_size: 50, pages: 3,
  has_next: true, ...over,
});

async function renderRuns(envelope: Page<RunOut>,
                          sp: Record<string, string | undefined> = {}) {
  apiGetMock.mockResolvedValueOnce(envelope);
  render(await RunsPage({ searchParams: Promise.resolve(sp) }));
}

afterEach(() => apiGetMock.mockReset());

it("shows which page of runs is on screen", async () => {
  // Without this, runs past the first 50 were unreachable with no affordance
  // to reach them -- /runs rendered `data.items` and nothing else, while
  // /leads had full controls over the identical Page<T> envelope.
  await renderRuns(page());
  expect(screen.getByText(/page 1 of 3/i)).toBeInTheDocument();
});

it("offers a next page while the API says there is one", async () => {
  await renderRuns(page());
  expect(screen.getByRole("link", { name: "Next" }))
    .toHaveAttribute("href", "/runs?page=2");
});

it("asks the API for the page in the URL", async () => {
  await renderRuns(page({ page: 2, has_next: false }), { page: "2" });
  expect(apiGetMock).toHaveBeenCalledWith("/runs",
    expect.objectContaining({ page: 2 }));
  expect(screen.getByRole("link", { name: "Previous" }))
    .toHaveAttribute("href", "/runs?page=1");
});

it("disables both controls, as buttons not links, on a single page", async () => {
  await renderRuns(page({ total: 2, pages: 1, has_next: false }));
  expect(screen.queryByRole("link", { name: "Next" })).toBeNull();
  expect(screen.getByRole("button", { name: "Next" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
});

it("reports the run total, not just the page", async () => {
  await renderRuns(page());
  expect(screen.getByText(/120 runs/i)).toBeInTheDocument();
});

it("still renders the API's message when the runs list cannot be fetched", async () => {
  apiGetMock.mockRejectedValueOnce(new MockApiError(0, "Cannot reach the API. Is it running?"));
  render(await RunsPage({ searchParams: Promise.resolve({}) }));
  expect(screen.getByRole("alert")).toHaveTextContent(/cannot reach the api/i);
});
