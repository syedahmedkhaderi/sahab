"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Menu, X, LogOut, Settings, LayoutDashboard, CreditCard, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Wordmark } from "@/components/Wordmark";
import { useToast } from "@/components/ui/toast";
import { auth } from "@/lib/api";
import type { User } from "@/lib/types";
import { cn } from "@/lib/utils";

interface NavProps {
  user: User | null;
}

const navLinks = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/billing", label: "Billing", icon: CreditCard },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Nav({ user }: NavProps) {
  const pathname = usePathname();
  const { toast } = useToast();
  const [menuOpen, setMenuOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);

  /**
   * Sign out, for real.
   *
   * Two things here are deliberate, and this used to get both wrong.
   *
   * The failure is not swallowed. Only the server can clear the session
   * cookie, because it is HttpOnly. Navigating to /login after a failed
   * logout left the cookie valid, and the middleware's "signed-in users do
   * not see /login" rule bounced the user straight back to /dashboard — a
   * sign-out that visibly did nothing and said nothing.
   *
   * The navigation is a hard one, not router.push. Next's client Router Cache
   * keys entries by URL, and while signed in the middleware redirects /login
   * to /dashboard — so a prefetch of the landing page's "Sign in" link can
   * leave the dashboard payload cached under /login for minutes. router.push
   * would then replay it with no request and no middleware run. Reloading the
   * document drops that cache and the whole client tree, and it fixes the
   * Back button for the same reason.
   */
  const handleLogout = async () => {
    setSigningOut(true);
    try {
      await auth.logout();
    } catch {
      toast({
        tone: "error",
        title: "Could not sign out",
        description:
          "Your session is still active. Check your connection and try again.",
      });
      setSigningOut(false);
      return;
    }
    setMenuOpen(false);
    window.location.assign("/login");
  };

  return (
    <nav className="sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur-sm supports-[backdrop-filter]:bg-background/75">
      <div className="mx-auto flex h-14 max-w-content items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        <Link href={user ? "/dashboard" : "/"} className="rounded-sm">
          <Wordmark />
        </Link>

        {/* Desktop nav */}
        {user && (
          <div className="hidden items-center gap-1 md:flex">
            {navLinks.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                aria-current={pathname.startsWith(href) ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-sm font-medium transition-colors",
                  pathname.startsWith(href)
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4" aria-hidden="true" />
                {label}
              </Link>
            ))}
            {user.role === "admin" && (
              <Link
                href="/admin"
                aria-current={pathname.startsWith("/admin") ? "page" : undefined}
                className={cn(
                  "flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-sm font-medium transition-colors",
                  pathname.startsWith("/admin")
                    ? "text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                Admin
              </Link>
            )}
          </div>
        )}

        {/* Right side */}
        <div className="flex items-center gap-2">
          {user ? (
            <>
              <span className="hidden max-w-[16rem] truncate text-sm text-muted-foreground lg:block">
                {user.email}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleLogout}
                loading={signingOut}
                className="hidden md:inline-flex"
              >
                {!signingOut && <LogOut className="h-4 w-4" aria-hidden="true" />}
                {signingOut ? "Signing out" : "Sign out"}
              </Button>
              {/* Mobile hamburger */}
              <button
                type="button"
                className="rounded-sm p-2 text-muted-foreground hover:bg-accent md:hidden"
                onClick={() => setMenuOpen(!menuOpen)}
                aria-expanded={menuOpen}
                aria-label={menuOpen ? "Close menu" : "Open menu"}
              >
                {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
              </button>
            </>
          ) : (
            <>
              <Link href="/login">
                <Button variant="ghost" size="sm">
                  Sign in
                </Button>
              </Link>
              <Link href="/signup">
                <Button size="sm">Request an account</Button>
              </Link>
            </>
          )}
        </div>
      </div>

      {/* Mobile menu */}
      {user && menuOpen && (
        <div className="border-t border-border bg-background px-4 py-3 md:hidden">
          <div className="mx-auto flex max-w-content flex-col gap-1">
            {navLinks.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                onClick={() => setMenuOpen(false)}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  pathname.startsWith(href)
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
                )}
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            ))}
            {user.role === "admin" && (
              <Link
                href="/admin"
                onClick={() => setMenuOpen(false)}
                className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              >
                <ShieldCheck className="h-4 w-4" />
                Admin
              </Link>
            )}
            <button
              type="button"
              onClick={handleLogout}
              disabled={signingOut}
              className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-60"
            >
              <LogOut className="h-4 w-4" />
              {signingOut ? "Signing out" : "Sign out"}
            </button>
          </div>
        </div>
      )}
    </nav>
  );
}
