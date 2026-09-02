import { when } from "@/lib/format";

/** Verbatim review text, easy to copy into outreach (spec section 9). */
export function EvidenceQuote({ text, rating, publishedAt }: {
  text: string; rating: number | null; publishedAt: string | null;
}) {
  return (
    <figure className="border-l-2 pl-3">
      <blockquote className="text-sm italic">&ldquo;{text}&rdquo;</blockquote>
      <figcaption className="mt-1 text-xs text-muted-foreground">
        {rating !== null && <span>{rating}★ · </span>}
        <span>{when(publishedAt)}</span>
      </figcaption>
    </figure>
  );
}
