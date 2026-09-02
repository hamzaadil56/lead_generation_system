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

it("says the API is unreachable instead of crashing to a blank 500", async () => {
  // The only screen of the four whose fetches were unguarded: with the API
  // down it returned HTTP 500 with no visible error text, while /leads,
  // /leads/[cid] and /runs all rendered "Cannot reach the API".
  apiGetMock.mockRejectedValueOnce(new MockApiError(0, "Cannot reach the API. Is it running?"));
  const jsx = await NewSearch({ searchParams: Promise.resolve({}) });
  render(jsx);
  expect(screen.getByRole("alert")).toHaveTextContent(/cannot reach the api/i);
});

it("does not show the form when the dropdown options could not be loaded", async () => {
  apiGetMock.mockRejectedValueOnce(new MockApiError(500, "The server hit an error. Try again."));
  const jsx = await NewSearch({ searchParams: Promise.resolve({}) });
  render(jsx);
  expect(screen.queryByRole("button", { name: "Preview" })).toBeNull();
});
