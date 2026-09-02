// @vitest-environment jsdom
import { render, screen, within } from "@testing-library/react";
import { expect, it } from "vitest";
import { ConfirmPanel } from "@/components/new-search-form";
import type { PreviewOut } from "@/lib/types";

const preview = (o: Partial<PreviewOut> = {}): PreviewOut => ({
  vertical: "hvac",
  queries: ["hvac contractor in Houston, TX", "ac repair in Houston, TX"],
  search_count: 2, estimated_results: 40,
  estimated_cost_usd: 0.012, recently_run_queries: [], ...o,
});

it("shows the expansion as a count of searches", () => {
  render(<ConfirmPanel preview={preview()} />);
  expect(screen.getByText(/2 searches/i)).toBeInTheDocument();
});

it("labels the cost as SEARCH cost, never as the total", () => {
  render(<ConfirmPanel preview={preview()} />);
  expect(screen.getByText(/estimated search cost/i)).toBeInTheDocument();
  // "Estimated cost" alone would overstate what the number covers.
  expect(screen.queryByText(/^estimated cost$/i)).toBeNull();
});

it("says scraping is not included in that figure", () => {
  render(<ConfirmPanel preview={preview()} />);
  expect(screen.getByText(/scraping .* not included|excludes .* scraping/i))
    .toBeInTheDocument();
});

it("warns about queries already run recently", () => {
  render(<ConfirmPanel preview={preview({
    recently_run_queries: ["hvac contractor in Houston, TX"],
  })} />);
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent(/already run/i);
  // The same query text also appears in the always-rendered queries list
  // below, so scope the lookup to the alert to keep this assertion
  // unambiguous (a bare screen.getByText matches both and throws).
  expect(within(alert).getByText(/hvac contractor in Houston, TX/)).toBeInTheDocument();
});

it("shows no warning when nothing was run recently", () => {
  render(<ConfirmPanel preview={preview()} />);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("shows the estimated result count", () => {
  render(<ConfirmPanel preview={preview({ estimated_results: 40 })} />);
  expect(screen.getByText(/40/)).toBeInTheDocument();
});
