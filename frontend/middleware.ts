import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Routes that require authentication (cookie presence check only —
// the real auth guard is the API returning 401 which the layout handles).
const AUTHED_PREFIXES = ["/dashboard", "/launch", "/billing", "/settings", "/admin", "/sessions"];
const PUBLIC_ONLY = ["/login", "/signup", "/verify"];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Best-effort: check for the session cookie set by FastAPI on login.
  // Must match the cookie name the backend sets (see make_session_cookie_kwargs).
  const hasSession = request.cookies.has("session_token");

  const isAuthedRoute = AUTHED_PREFIXES.some((prefix) =>
    pathname.startsWith(prefix)
  );
  const isPublicOnly = PUBLIC_ONLY.some((prefix) => pathname.startsWith(prefix));

  // Redirect unauthenticated users away from protected routes
  if (isAuthedRoute && !hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Redirect authenticated users away from login/signup
  if (isPublicOnly && hasSession) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Match all routes except Next.js internals and static files
    "/((?!_next/static|_next/image|favicon.ico|robots.txt).*)",
  ],
};
