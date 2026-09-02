"use client";
import { useActionState } from "react";
import { queueRun, type QueueState } from "@/app/runs/new/actions";
import type { RunCreate } from "@/lib/types";
import { Button } from "@/components/ui/button";

const initialState: QueueState = { error: null };

/**
 * The button that actually spends money. A failed queueRun() returns
 * { error } instead of throwing or redirecting, so a transient API failure
 * renders as text here rather than crashing to Next's error page or
 * silently sending the user to /runs as if it had worked.
 */
export function QueueRunForm({ body }: { body: RunCreate }) {
  const [state, formAction, pending] = useActionState(
    (prevState: QueueState) => queueRun(body, prevState),
    initialState,
  );

  return (
    <form action={formAction} className="space-y-2">
      {state.error && (
        <p role="alert" className="text-sm text-destructive">{state.error}</p>
      )}
      <Button type="submit" disabled={pending}>
        {pending ? "Starting…" : "Start this run"}
      </Button>
    </form>
  );
}
