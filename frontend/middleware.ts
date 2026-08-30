import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { jwtVerify } from "jose";

// Routes that require a signed-in user. The API is the authority on access —
// it returns 401/403 regardless of what the browser does — but a page should
// not render its shell to someone who will only be bounced out of it.
const AUTHED_PREFIXES = ["/dashboard", "/launch", "/billing", "/settings", "/admin", "/sessions"];
const PUBLIC_ONLY = ["/login", "/signup", "/verify"];
const ADMIN_PREFIXES = ["/admin"];

// Must match JWT_SECRET in the backend .env — the same key signs this token.
const secret = new TextEncoder().encode(process.env.JWT_SECRET ?? "");

type SessionClaims = {
  sub?: string;
  role?: string;
};

/**
 * Verify the session cookie and return its claims.
 *
 * A cookie that is merely present proves nothing: it can be expired, forged, or
 * signed by a different deployment. Checking the signature is what makes the
 * role claim below worth reading.
 */
async function readSession(token: string | undefined): Promise<SessionClaims | null> {
  if (!token || secret.length === 0) return null;
  try {
    const { payload } = await jwtVerify(token, secret, { algorithms: ["HS256"] });
    return payload as SessionClaims;
  } catch {
    // Expired, tampered with, or signed by another key — all mean "not signed in".
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  const session = await readSession(request.cookies.get("session_token")?.value);
  const isAuthedRoute = AUTHED_PREFIXES.some((prefix) => pathname.startsWith(prefix));
  const isPublicOnly = PUBLIC_ONLY.some((prefix) => pathname.startsWith(prefix));
  const isAdminRoute = ADMIN_PREFIXES.some((prefix) => pathname.startsWith(prefix));

  // Redirect unauthenticated users away from protected routes
  if (isAuthedRoute && !session) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    const response = NextResponse.redirect(loginUrl);
    // Clear a cookie that no longer verifies, so the user is not bounced
    // between /login and /dashboard by the rule below.
    response.cookies.delete("session_token");
    return response;
  }

  // A student reaching /admin used to get the full console shell, and only the
  // client-side role check sent them away. Decide it here instead, so the page
  // never renders. (Their data was never at risk — the API returns 403.)
  if (isAdminRoute && session?.role !== "admin") {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  // Redirect authenticated users away from login/signup
  if (isPublicOnly && session) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    // Match all routes except Next.js internals and static files
    "/((?!_next/static|_next/image|favicon.ico|icon.svg|robots.txt).*)",
  ],
};
