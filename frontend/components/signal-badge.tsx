import { Badge } from "@/components/ui/badge";
import { humanise } from "@/lib/format";

/** A null signal means UNKNOWN, not false. The pipeline's whole scoring model
 *  turns on that distinction (ADR-005), so this component refuses to collapse
 *  the two into one appearance. */
export function SignalBadge({ name, value }: { name: string; value: unknown }) {
  const unknown = value === null || value === undefined;
  const label = unknown ? "unknown"
    : typeof value === "boolean" ? (value ? "yes" : "no")
    : String(value);

  return (
    <Badge variant={unknown ? "outline" : value === false ? "secondary" : "default"}
           className={unknown ? "border-dashed text-muted-foreground" : ""}>
      <span>{humanise(name)}</span>: <span>{label}</span>
    </Badge>
  );
}
