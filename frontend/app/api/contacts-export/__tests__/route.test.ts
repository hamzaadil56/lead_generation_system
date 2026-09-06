import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { LEAD_FILTER_KEYS } from "@/lib/filters";

const apiGetRawMock = vi.fn();
class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({
  apiGetRaw: apiGetRawMock, ApiError: MockApiError,
}));

const { GET } = await import("@/app/api/contacts-export/route");

afterEach(() => apiGetRawMock.mockReset());

const call = async (query: string) => {
  apiGetRawMock.mockResolvedValueOnce(new Response("name\n"));
  await GET(new NextRequest(`http://localhost/api/contacts-export?${query}`));
  return apiGetRawMock.mock.calls[0][1] as Record<string, string | undefined>;
};

it("forwards every lead filter, not a hand-picked subset", async () => {
  // A dropped filter does not error — it exports the whole table under a URL
  // that says otherwise. This is the bug commit f7b1ef2 fixed for leads, and
  // ADR-level comments on both endpoints say the blast radius is larger here.
  const params = await call(LEAD_FILTER_KEYS.map((k) => `${k}=v`).join("&"));
  for (const key of LEAD_FILTER_KEYS) {
    expect(params).toMatchObject({ [key]: "v" });
  }
});

it("forwards nothing that was not asked for", async () => {
  const params = await call("quadrant=go_now");
  expect(Object.values(params).filter((v) => v !== undefined)).toEqual(["go_now"]);
});

it("hits the contacts CSV endpoint", async () => {
  await call("quadrant=go_now");
  expect(apiGetRawMock).toHaveBeenCalledWith("/contacts/export.csv", expect.anything());
});

it("names the download contacts.csv", async () => {
  apiGetRawMock.mockResolvedValueOnce(new Response("name\n"));
  const res = await GET(new NextRequest("http://localhost/api/contacts-export"));
  expect(res.headers.get("content-disposition")).toContain('filename="contacts.csv"');
});

it("turns an upstream failure into a safe error response", async () => {
  apiGetRawMock.mockRejectedValueOnce(new MockApiError(502, "boom"));
  const res = await GET(new NextRequest("http://localhost/api/contacts-export"));
  expect(res.status).toBe(502);
});
