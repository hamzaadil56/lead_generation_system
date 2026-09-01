import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { ApiError, apiGet, apiSend } from "@/lib/api";

const originalFetch = global.fetch;

beforeEach(() => {
  process.env.API_BASE_URL = "http://api:8000";
  process.env.API_KEY = "test-key";
});
afterEach(() => { global.fetch = originalFetch; vi.restoreAllMocks(); });

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400, status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
  global.fetch = fn as unknown as typeof fetch;
  return fn;
}

it("sends the API key as a header", async () => {
  const fn = mockFetch(200, { ok: true });
  await apiGet("/health");
  const [, init] = fn.mock.calls[0];
  expect(init.headers["X-API-Key"]).toBe("test-key");
});

it("never puts the API key in the URL", async () => {
  const fn = mockFetch(200, { ok: true });
  await apiGet("/leads", { quadrant: "go_now" });
  const [url] = fn.mock.calls[0];
  expect(String(url)).not.toContain("test-key");
});

it("omits undefined query params rather than sending the string 'undefined'", async () => {
  const fn = mockFetch(200, { ok: true });
  await apiGet("/leads", { quadrant: "go_now", state: undefined, page: 2 });
  const url = String(fn.mock.calls[0][0]);
  expect(url).toContain("quadrant=go_now");
  expect(url).toContain("page=2");
  expect(url).not.toContain("state");
});

it("throws ApiError carrying the status and the backend's detail", async () => {
  mockFetch(404, { detail: "no such lead: abc" });
  await expect(apiGet("/leads/abc")).rejects.toMatchObject({
    status: 404, detail: "no such lead: abc",
  });
});

it("does not echo a 422 field-error array as the message", async () => {
  mockFetch(422, { detail: [{ loc: ["body", "pages"], msg: "too big" }] });
  await expect(apiSend("POST", "/runs", {})).rejects.toMatchObject({
    status: 422,
  });
  // The raw array must not become the user-facing string.
  await apiSend("POST", "/runs", {}).catch((e: ApiError) => {
    expect(e.detail).not.toContain("loc");
  });
});

it("surfaces a network failure as ApiError, not a raw TypeError", async () => {
  global.fetch = vi.fn().mockRejectedValue(new TypeError("fetch failed")) as never;
  await expect(apiGet("/health")).rejects.toBeInstanceOf(ApiError);
});

it("refuses to run if API_KEY is unset", async () => {
  delete process.env.API_KEY;
  mockFetch(200, {});
  await expect(apiGet("/health")).rejects.toThrow(/API_KEY/);
});
