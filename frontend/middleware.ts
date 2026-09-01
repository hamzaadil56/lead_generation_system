import { NextRequest, NextResponse } from "next/server";
import { SESSION_COOKIE, verifySession } from "@/lib/auth";

export async function middleware(req: NextRequest) {
  if (await verifySession(req.cookies.get(SESSION_COOKIE)?.value)) {
    return NextResponse.next();
  }
  const login = new URL("/login", req.url);
  login.searchParams.set("next", req.nextUrl.pathname);
  return NextResponse.redirect(login);
}

export const config = {
  // Everything except the login page and Next's own assets. The matcher is
  // the whole gate -- a screen added outside it is silently public.
  matcher: ["/((?!login|_next/static|_next/image|favicon\\.ico).*)"],
};
