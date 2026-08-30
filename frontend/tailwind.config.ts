import type { Config } from "tailwindcss";

/**
 * Every colour here resolves to a CSS variable defined in app/globals.css, so
 * light and dark stay one system. A literal colour in a component (bg-blue-100,
 * bg-green-100) is outside the system and is what broke dark mode before.
 */
const config: Config = {
  darkMode: ["class"],
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
          hover: "hsl(var(--primary-hover))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        // Semantic state colours. `subtle` is the tinted background a badge or
        // alert sits on; `strong` is the text colour that stays legible on it.
        success: {
          DEFAULT: "hsl(var(--success))",
          foreground: "hsl(var(--success-foreground))",
          subtle: "hsl(var(--success-subtle))",
          strong: "hsl(var(--success-strong))",
        },
        warning: {
          DEFAULT: "hsl(var(--warning))",
          foreground: "hsl(var(--warning-foreground))",
          subtle: "hsl(var(--warning-subtle))",
          strong: "hsl(var(--warning-strong))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
          subtle: "hsl(var(--destructive-subtle))",
          strong: "hsl(var(--destructive-strong))",
        },
        info: {
          DEFAULT: "hsl(var(--info))",
          subtle: "hsl(var(--info-subtle))",
          strong: "hsl(var(--info-strong))",
        },
        border: {
          DEFAULT: "hsl(var(--border))",
          strong: "hsl(var(--border-strong))",
        },
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        // Loaded through next/font in app/layout.tsx, which sets these vars.
        // JetBrains Mono used to be declared here and never loaded, so every
        // font-mono number silently fell back to Menlo.
        sans: ["var(--font-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "ui-monospace", "Menlo", "monospace"],
      },
      // A fixed rem scale, not fluid: this is product UI viewed at a consistent
      // DPI, and a heading that shrinks inside a panel looks worse, not better.
      // Ratio is ~1.15 between steps — enough contrast to read as hierarchy,
      // tight enough not to add noise across many labels.
      fontSize: {
        xs: ["0.75rem", { lineHeight: "1rem", letterSpacing: "0.01em" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.9375rem", { lineHeight: "1.5rem" }],
        lg: ["1.0625rem", { lineHeight: "1.625rem", letterSpacing: "-0.01em" }],
        xl: ["1.1875rem", { lineHeight: "1.75rem", letterSpacing: "-0.015em" }],
        "2xl": ["1.4375rem", { lineHeight: "2rem", letterSpacing: "-0.02em" }],
        "3xl": ["1.75rem", { lineHeight: "2.25rem", letterSpacing: "-0.022em" }],
        "4xl": ["2.125rem", { lineHeight: "2.5rem", letterSpacing: "-0.025em" }],
        "5xl": ["2.75rem", { lineHeight: "3rem", letterSpacing: "-0.03em" }],
      },
      // One container width for every page. Five different max-widths were in
      // use with no rule, so pages disagreed about where the content edge was.
      maxWidth: {
        content: "72rem",
        prose: "42rem",
        form: "26rem",
      },
      boxShadow: {
        // Borders carry structure here; shadows only lift things that float.
        // Each has a real offset and blur — a zero-offset halo is decoration.
        popover: "0 4px 12px -2px hsl(0 0% 0% / 0.10), 0 2px 4px -2px hsl(0 0% 0% / 0.06)",
        raised: "0 1px 2px 0 hsl(0 0% 0% / 0.05)",
      },
      transitionDuration: {
        // Users are in a task; state changes read as instant feedback.
        DEFAULT: "150ms",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-in": "fade-in 150ms ease-out",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};
export default config;
