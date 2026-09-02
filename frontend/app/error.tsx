"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

/**
 * Backstop for any screen whose own try/catch misses something. Every screen
 * guards its own fetches and renders the API's message inline, which is the
 * better experience; this boundary exists so that a screen which later grows
 * an unguarded call degrades to readable text instead of a blank HTTP 500,
 * the way /runs/new once did.
 *
 * It deliberately shows no error detail: `error.message` on the server is
 * replaced by a digest in production, and showing raw text would risk
 * surfacing internals to the browser.
 */
export default function Error({ error, reset }: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => { console.error(error); }, [error]);

  return (
    <div className="space-y-4 py-12 text-center">
      <p role="alert" className="text-destructive">
        Something went wrong on this screen.
      </p>
      {error.digest && (
        <p className="font-mono text-xs text-muted-foreground">{error.digest}</p>
      )}
      <Button variant="outline" onClick={reset}>Try again</Button>
    </div>
  );
}
