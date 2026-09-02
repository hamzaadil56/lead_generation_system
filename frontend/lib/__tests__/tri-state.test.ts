import { expect, it } from "vitest";
import { triStateToBool, triStateValue, TRI_STATES } from "@/lib/tri-state";

it("offers exactly three states, in the SignalBadge vocabulary", () => {
  expect([...TRI_STATES]).toEqual(["unknown", "yes", "no"]);
});

it("preselects the stored value, and unknown when nothing is stored", () => {
  expect(triStateValue(true)).toBe("yes");
  expect(triStateValue(false)).toBe("no");
  // The bug this replaces: `?? false` rendered both of these as "no".
  expect(triStateValue(null)).toBe("unknown");
  expect(triStateValue(undefined)).toBe("unknown");
});

it("sends null for unknown rather than an explicit false", () => {
  expect(triStateToBool("yes")).toBe(true);
  expect(triStateToBool("no")).toBe(false);
  expect(triStateToBool("unknown")).toBeNull();
});

it("never writes false for a value the form did not post", () => {
  // A checkbox posts nothing when unticked, which is how the old form turned
  // "unknown" into an explicit false on every save.
  expect(triStateToBool(null)).toBeNull();
  expect(triStateToBool("")).toBeNull();
  expect(triStateToBool("on")).toBeNull();
});
