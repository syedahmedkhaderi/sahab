import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const siteName = process.env.NEXT_PUBLIC_SITE_NAME ?? "Sahab";

// Self-hosted at build time by next/font: no render-blocking request to
// fonts.googleapis.com, no layout shift, and JetBrains Mono actually arrives.
// It was declared in the Tailwind config but never loaded, so every GPU UUID,
// credit balance and duration silently rendered in Menlo.
const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: {
    default: siteName,
    template: `%s · ${siteName}`,
  },
  description:
    "GPU workspaces for students and researchers at the University of Doha for Science and Technology.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${inter.variable} ${jetbrainsMono.variable} min-h-screen bg-background font-sans antialiased`}
      >
        {/*
          THESIS: Sahab is university infrastructure, not a startup landing
          page. It refuses the centred marketing hero and the same-size feature
          card grid; the page states what the hardware is and hands you the
          action.
          OWN-WORLD: UDST royal blue (#0055B8) on a warm grey canvas, white
          surfaces, hairline borders instead of shadows, a tight 6px radius, one
          sans for everything and JetBrains Mono for every measured number.
          Recognizable with all content removed by the warmth of its greys and
          the flatness of its panels.
          STORY: a student sees real hardware they can have in a minute,
          understands they sign in with their UDST email, and launches.
          FIRST VIEWPORT: left-aligned heading, one paragraph of plain English,
          the primary action inline beside a secondary; the live GPU status
          panel sits to the right on desktop and directly under the action on
          mobile.
          FORM: brief-pinned (UDST palette, Vercel register, Operate mode) —
          this direction was specified rather than dealt.
          FINISH: unreviewed and undocumented is unfinished; this build ends
          with the finish review, the verdict, DESIGN.md, and every shipping
          raster carrying its provenance.
        */}
        {children}
      </body>
    </html>
  );
}
