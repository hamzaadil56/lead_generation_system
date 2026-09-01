import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { SESSION_COOKIE, signSession } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export default async function Login({
  searchParams,
}: { searchParams: Promise<{ next?: string; error?: string }> }) {
  const { next = "/leads", error } = await searchParams;

  async function submit(form: FormData) {
    "use server";
    const target = String(form.get("next") || "/leads");
    try {
      const token = await signSession(String(form.get("password") ?? ""));
      (await cookies()).set(SESSION_COOKIE, token, {
        httpOnly: true, sameSite: "lax", path: "/",
        secure: process.env.NODE_ENV === "production",
      });
    } catch {
      redirect(`/login?error=1&next=${encodeURIComponent(target)}`);
    }
    redirect(target);
  }

  return (
    <form action={submit} className="mx-auto mt-24 max-w-sm space-y-4">
      <h1 className="text-xl font-semibold">Sign in</h1>
      <input type="hidden" name="next" value={next} />
      <div className="space-y-2">
        <Label htmlFor="password">Password</Label>
        <Input id="password" name="password" type="password" required autoFocus />
      </div>
      {error && <p role="alert" className="text-sm text-destructive">
        That password was not right.
      </p>}
      <Button type="submit" className="w-full">Sign in</Button>
    </form>
  );
}
