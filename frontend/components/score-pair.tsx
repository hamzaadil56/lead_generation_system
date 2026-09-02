/** Fit and pain are independent axes (ADR-004). This component exists so that
 *  showing one without the other requires going out of your way. */
export function ScorePair({ fit, pain }: { fit: number; pain: number }) {
  return (
    <span className="inline-flex items-center gap-1 font-mono tabular-nums"
          aria-label={`Fit ${fit}, pain ${pain}`}>
      <span className="text-sky-600 dark:text-sky-400">{fit}</span>
      <span className="text-muted-foreground">/</span>
      <span className="text-amber-600 dark:text-amber-400">{pain}</span>
    </span>
  );
}
