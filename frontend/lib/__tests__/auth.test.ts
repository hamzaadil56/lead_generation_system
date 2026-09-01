import { beforeEach, expect, it } from "vitest";
import { signSession, verifySession } from "@/lib/auth";

beforeEach(() => {
  process.env.DASHBOARD_PASSWORD = "correct horse";
  process.env.SESSION_SECRET = "a-secret-at-least-32-characters-long!!";
});

it("accepts a token it just issued", async () => {
  expect(await verifySession(await signSession("correct horse"))).toBe(true);
});

it("rejects a wrong password at signing time", async () => {
  await expect(signSession("wrong")).rejects.toThrow();
});

it("rejects a missing token", async () => {
  expect(await verifySession(undefined)).toBe(false);
});

it("rejects a tampered token", async () => {
  const good = await signSession("correct horse");
  expect(await verifySession(good.slice(0, -3) + "aaa")).toBe(false);
});

it("rejects a token signed with a different secret", async () => {
  const token = await signSession("correct horse");
  process.env.SESSION_SECRET = "a-completely-different-secret-value!!!";
  expect(await verifySession(token)).toBe(false);
});

it("refuses to operate when DASHBOARD_PASSWORD is unset", async () => {
  delete process.env.DASHBOARD_PASSWORD;
  await expect(signSession("anything")).rejects.toThrow(/DASHBOARD_PASSWORD/);
});
