"use client";
import { useTransition } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";

export type HarvestResult = { created: number | null; error: string | null };

/** The leads-list bulk harvest button. `action` is a server action closed
 *  over the SAME filter object the leads-list export link is built from
 *  (see app/leads/page.tsx) -- deriving the two from one object is what
 *  keeps this button's blast radius matching what the screen shows, rather
 *  than repeating the bug that once let the export quietly cover the whole
 *  table (commit f7b1ef2). */
export function HarvestContactsButton({ action }: {
  action: () => Promise<HarvestResult>;
}) {
  const [pending, startTransition] = useTransition();

  function onClick() {
    startTransition(async () => {
      const { created, error } = await action();
      if (error) {
        toast.error(error);
      } else {
        toast.success(
          `Harvested ${created} new contact${created === 1 ? "" : "s"}.`);
      }
    });
  }

  return (
    <Button type="button" size="sm" variant="secondary" onClick={onClick} disabled={pending}>
      {pending ? "Harvesting…" : "Harvest emails"}
    </Button>
  );
}
