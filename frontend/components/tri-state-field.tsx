import { Label } from "@/components/ui/label";
import { TRI_STATES, triStateValue } from "@/lib/tri-state";

/** A three-state control for a `bool | null` manual fact.
 *
 *  Not a checkbox: a checkbox has two states and would collapse "unknown"
 *  into "no" on the way in and back out again. See lib/tri-state.ts. */
export function TriStateField({ name, label, value }: {
  name: string;
  label: string;
  value: boolean | null | undefined;
}) {
  return (
    <div className="space-y-2">
      <Label htmlFor={name}>{label}</Label>
      <select id={name} name={name} defaultValue={triStateValue(value)}
              className="w-full rounded-md border bg-background p-2">
        {TRI_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
    </div>
  );
}
