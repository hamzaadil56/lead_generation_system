import { Badge } from "@/components/ui/badge";
import { humanise } from "@/lib/format";

// The four semantic tokens of the scoring vocabulary (spec section 9).
const STYLES: Record<string, string> = {
  go_now:  "bg-emerald-600 text-white hover:bg-emerald-600",
  nurture: "bg-sky-600 text-white hover:bg-sky-600",
  low_fit: "bg-amber-600 text-white hover:bg-amber-600",
  cold:    "bg-slate-500 text-white hover:bg-slate-500",
};

export function QuadrantBadge({ quadrant }: { quadrant: string }) {
  return <Badge className={STYLES[quadrant] ?? STYLES.cold}>
    {humanise(quadrant)}
  </Badge>;
}
