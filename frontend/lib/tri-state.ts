/** The three states a `bool | null` manual fact can hold.
 *
 *  `has_office_admin` and `owner_growth_focused` are `Mapped[bool | None]` in
 *  the database and `bool | None` in both `ManualFactsIn` and
 *  `ManualFactsOut`. A checkbox has two states, so rendering them as one
 *  destroys the difference between "nobody has researched this" (null) and
 *  "researched, the answer is no" (false) -- the distinction ADR-005 makes
 *  the whole scoring model turn on, in `manual_facts`, the one table a
 *  pipeline rerun must never rebuild.
 *
 *  The vocabulary is deliberately the same one `SignalBadge` renders
 *  ("unknown" / "yes" / "no") so the form a person types into and the Signals
 *  card that reads the result back say the same words.
 */
export const TRI_STATES = ["unknown", "yes", "no"] as const;

export type TriState = (typeof TRI_STATES)[number];

/** Stored value -> the option to preselect. `null` and `undefined` (no
 *  manual_facts row at all) both mean unknown. */
export function triStateValue(stored: boolean | null | undefined): TriState {
  return stored === true ? "yes" : stored === false ? "no" : "unknown";
}

/** Posted option -> what to send the API. Anything that is not an explicit
 *  yes/no is `null`: a missing or unrecognised value must never be written
 *  as `false`. */
export function triStateToBool(posted: FormDataEntryValue | null): boolean | null {
  return posted === "yes" ? true : posted === "no" ? false : null;
}
