// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("@/components/queue-run-form", () => ({
  QueueRunForm: () => null,
}));

const apiGetMock = vi.fn(async (path: string) => {
  if (path === "/verticals") return [{ name: "hvac", search_terms: [], ruleset: "x" }];
  if (path === "/states") return [{ code: "tx", metros: ["Houston"] }];
  return [];
});
const apiSendMock = vi.fn();
class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({
  apiGet: apiGetMock,
  apiSend: apiSendMock,
  ApiError: MockApiError,
}));

const { default: NewSearch } = await import("@/app/runs/new/page");

it("tells the user to choose a state or location instead of silently doing nothing", async () => {
  const jsx = await NewSearch({ searchParams: Promise.resolve({ confirm: "1" }) });
  render(jsx);
  expect(screen.getByRole("alert")).toHaveTextContent(/choose a state or a location/i);
  // Neither should it have sent a request the API would 422 on.
  expect(apiSendMock).not.toHaveBeenCalled();
});

it("does not show that message once a state is chosen and previews normally", async () => {
  apiSendMock.mockResolvedValueOnce({
    vertical: "hvac", queries: ["hvac contractor in tx"], search_count: 1,
    estimated_results: 10, estimated_cost_usd: 0.006, recently_run_queries: [],
  });
  const jsx = await NewSearch({
    searchParams: Promise.resolve({ confirm: "1", state: "tx" }),
  });
  render(jsx);
  expect(screen.queryByText(/choose a state or a location/i)).toBeNull();
});
