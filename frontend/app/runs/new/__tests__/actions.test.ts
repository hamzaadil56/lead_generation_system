import { afterEach, expect, it, vi } from "vitest";

/** Next's real `redirect()` does not return -- it throws a `NEXT_REDIRECT`
 *  control-flow signal that the framework unwinds. A plain, non-throwing
 *  `vi.fn()` therefore let `queueRun` behave in the test in a way it never
 *  behaves in production: with the mock silent, moving `redirect()` back
 *  inside the try/catch (the exact regression the money path's comment warns
 *  against) still passed all three tests, because nothing was thrown for the
 *  catch to swallow. The mock throws the same shape Next does. */
const redirectMock = vi.fn((url: string) => {
  const signal = new Error("NEXT_REDIRECT") as Error & { digest?: string };
  signal.digest = `NEXT_REDIRECT;replace;${url};307;`;
  throw signal;
});
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
  // The redirect signal must escape queueRun, not be caught by it.
  await expect(queueRun(body, { error: null })).rejects.toThrow("NEXT_REDIRECT");
  expect(redirectMock).toHaveBeenCalledTimes(1);
  expect(redirectMock).toHaveBeenCalledWith("/runs?highlight=42");
});

it("never reports a successful queue as a failure", async () => {
  // If redirect() is called inside the try/catch, its signal is caught and
  // returned as { error }, so the run IS queued -- money spent -- and the
  // screen tells the user it was not. That is the one outcome this action
  // exists to prevent.
  apiSendMock.mockResolvedValueOnce({ id: 42 });
  const outcome = await queueRun(body, { error: null }).catch((e) => e);
  expect(outcome).toBeInstanceOf(Error);
  expect((outcome as { digest?: string }).digest).toMatch(/^NEXT_REDIRECT/);
});
