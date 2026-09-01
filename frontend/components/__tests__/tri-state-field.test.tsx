// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { TriStateField } from "@/components/tri-state-field";

const field = (value: boolean | null | undefined) =>
  render(<TriStateField name="has_office_admin" label="Has an office admin"
                        value={value} />);

it("offers unknown as a choice, so null is reachable from the form", () => {
  field(null);
  const select = screen.getByLabelText("Has an office admin");
  expect([...select.querySelectorAll("option")].map((o) => o.textContent))
    .toEqual(["unknown", "yes", "no"]);
});

it.each([
  [true, "yes"], [false, "no"], [null, "unknown"], [undefined, "unknown"],
] as const)("prefills %s as %s", (stored, expected) => {
  field(stored);
  expect(screen.getByLabelText("Has an office admin")).toHaveValue(expected);
});

it("does not render a checkbox, which could only hold two of the three states", () => {
  const { container } = field(null);
  expect(container.querySelector('input[type="checkbox"]')).toBeNull();
});
