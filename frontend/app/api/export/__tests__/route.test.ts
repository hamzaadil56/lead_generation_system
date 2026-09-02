import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";

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

const { GET } = await import("@/app/api/export/route");

afterEach(() => apiGetRawMock.mockReset());

const call = async (query: string) => {
  apiGetRawMock.mockResolvedValueOnce(new Response("name\n"));
  await GET(new NextRequest(`http://localhost/api/export?${query}`));
  return apiGetRawMock.mock.calls[0][1] as Record<string, string | undefined>;
};

it("forwards every filter the export endpoint accepts", async () => {
  // The proxy forwarded quadrant and min_fit only. FastAPI ignores query
  // params an endpoint does not declare, so a filter dropped here fails
  // silently: the file is simply unfiltered.
  const params = await call(
    "quadrant=go_now&state=TX&outcome_status=contacted&min_fit=40&min_pain=30&vertical=hvac");
  expect(params).toMatchObject({
    quadrant: "go_now", state: "TX", outcome_status: "contacted",
    min_fit: "40", min_pain: "30", vertical: "hvac",
  });
});

it("forwards nothing that was not asked for", async () => {
  const params = await call("quadrant=go_now");
  expect(Object.values(params).filter((v) => v !== undefined)).toEqual(["go_now"]);
});
