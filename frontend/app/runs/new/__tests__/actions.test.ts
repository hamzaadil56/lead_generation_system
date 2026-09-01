import { afterEach, expect, it, vi } from "vitest";

const redirectMock = vi.fn();
vi.mock("next/navigation", () => ({ redirect: redirectMock }));

const apiSendMock = vi.fn();
class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({ apiSend: apiSendMock, ApiError: MockApiError }));

const { queueRun } = await import("@/app/runs/new/actions");

const body = { vertical: "hvac", state: "tx", location: null, pages: 5 };

afterEach(() => {
  redirectMock.mockClear();
  apiSendMock.mockClear();
});

it("shows a visible message and does not redirect when POST /runs fails", async () => {
  apiSendMock.mockRejectedValueOnce(new MockApiError(400, "Unknown vertical."));
  const state = await queueRun(body, { error: null });
  expect(state.error).toMatch(/unknown vertical/i);
  expect(redirectMock).not.toHaveBeenCalled();
});

it("falls back to a generic message when the failure isn't an ApiError", async () => {
  apiSendMock.mockRejectedValueOnce(new Error("boom"));
  const state = await queueRun(body, { error: null });
  expect(state.error).toMatch(/could not start the run/i);
  expect(redirectMock).not.toHaveBeenCalled();
});

it("redirects to the queued run when POST /runs succeeds", async () => {
  apiSendMock.mockResolvedValueOnce({ id: 42 });
  await queueRun(body, { error: null });
  expect(redirectMock).toHaveBeenCalledTimes(1);
  expect(redirectMock).toHaveBeenCalledWith("/runs?highlight=42");
});
