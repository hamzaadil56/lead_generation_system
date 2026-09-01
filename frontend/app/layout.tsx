import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import Link from "next/link";
import { ThemeToggle } from "@/components/theme-toggle";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

export const metadata: Metadata = { title: "Lead Dashboard" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
          <header className="border-b">
            <nav className="mx-auto flex max-w-7xl items-center gap-6 p-4">
              <Link href="/leads" className="font-semibold">Leads</Link>
              <Link href="/runs">Runs</Link>
              <Link href="/runs/new">New search</Link>
              <div className="ml-auto"><ThemeToggle /></div>
            </nav>
          </header>
          <main className="mx-auto max-w-7xl p-4">{children}</main>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
