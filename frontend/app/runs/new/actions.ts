"use server";

import { redirect } from "next/navigation";
import { apiSend, ApiError } from "@/lib/api";
import type { RunCreate, RunOut } from "@/lib/types";

export type QueueState = { error: string | null };

/**
 * Queue a run. This is the only call in the new-search flow that spends
 * money — POST /runs/preview, used to build the confirm panel, only reads
 * config and the local database.
 *
 * A transient failure here must show up as visible text on the page, not
 * as Next's raw error page, so failures are returned as state rather than
 * thrown. redirect() itself works by throwing a Next-internal control-flow
 * signal; it is called only on the success path, outside any try/catch, so
 * a successful queue is never mistaken for a failure.
 */
export async function queueRun(
  body: RunCreate,
  _prevState: QueueState,
): Promise<QueueState> {
  let run: RunOut;
  try {
    run = await apiSend<RunOut>("POST", "/runs", body);
  } catch (e) {
    return { error: e instanceof ApiError ? e.detail : "Could not start the run." };
  }
  redirect(`/runs?highlight=${run.id}`);
}
