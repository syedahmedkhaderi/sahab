import React from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Wordmark } from "@/components/Wordmark";
import { SiteHeader } from "@/components/SiteHeader";

const siteName = process.env.NEXT_PUBLIC_SITE_NAME ?? "Sahab";

// The hardware this platform actually runs on. Two L4s, and the page says two.
const HARDWARE = [
  { label: "GPUs", value: "2 × NVIDIA L4" },
  { label: "Memory per GPU", value: "24 GB" },
  { label: "Workspace storage", value: "50 GB, kept between sessions" },
  { label: "Environment", value: "JupyterLab, VS Code, PyTorch + CUDA" },
];

const STEPS = [
  {
    title: "Sign in with your UDST email",
    body: "Accounts are approved by the platform administrator before the first launch. Only udst.edu.qa addresses can register.",
  },
  {
    title: "Ask for a GPU workspace",
    body: "You choose whether you need a GPU and which environment to run. You do not choose which GPU — the scheduler assigns one that is genuinely free, and tells you plainly when there is none.",
  },
  {
    title: "Work in the browser",
    body: "JupyterLab opens with CUDA available. VS Code runs in the same container if you prefer it. Your files stay in place when the session ends.",
  },
  {
    title: "Stop when you are done",
    body: "Credits are metered per minute while a GPU session runs. Sessions left idle for 45 minutes stop on their own, so a forgotten tab does not hold a GPU.",
  },
];

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <SiteHeader>
        <Link href="/" className="rounded-sm">
          <Wordmark />
        </Link>
        <div className="flex items-center gap-1.5">
          <Button variant="ghost" size="sm" asChild>
            <Link href="/login">Sign in</Link>
          </Button>
          <Button size="sm" asChild>
            <Link href="/signup">Request an account</Link>
          </Button>
        </div>
      </SiteHeader>

      <main className="flex-1">
        {/* Opening. Left-aligned and factual: the specification sits beside the
            claim rather than under a centred marketing headline. */}
        <section className="border-b border-border px-4 py-14 sm:px-6 sm:py-20 lg:px-8">
          <div className="mx-auto grid max-w-content gap-10 lg:grid-cols-[minmax(0,1fr)_22rem] lg:gap-16">
            <div className="max-w-prose">
              <h1 className="text-balance text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">
                A GPU from the university, in a browser tab.
              </h1>
              <p className="mt-5 text-base text-muted-foreground">
                {siteName} gives students, researchers and faculty at the University
                of Doha for Science and Technology a JupyterLab workspace running on
                one of the university&rsquo;s NVIDIA L4 GPUs. You sign in with your
                UDST address and start working — there is nothing to install and no
                machine to configure.
              </p>
              <p className="mt-4 text-base text-muted-foreground">
                Two GPUs are shared across everyone who uses them, so time on one is
                metered in credits your department grants. When both are busy you are
                told so, and you can queue or take a CPU workspace instead.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Button size="lg" asChild>
                  <Link href="/signup">
                    Request an account
                    <ArrowRight className="h-4 w-4" aria-hidden="true" />
                  </Link>
                </Button>
                <Button variant="outline" size="lg" asChild>
                  <Link href="/login">I already have one</Link>
                </Button>
              </div>
            </div>

            {/* The specification, as a specification. */}
            <div className="self-start rounded-md border border-border bg-card">
              <div className="border-b border-border px-5 py-3">
                <h2 className="text-sm font-medium text-foreground">
                  What you get
                </h2>
              </div>
              <dl className="divide-y divide-border">
                {HARDWARE.map(({ label, value }) => (
                  <div key={label} className="px-5 py-3">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="mt-0.5 font-mono text-sm text-foreground">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          </div>
        </section>

        {/* How it works. A sequence, because the order genuinely matters. */}
        <section className="border-b border-border px-4 py-14 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-content">
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              How it works
            </h2>
            <ol className="mt-8 grid gap-x-12 gap-y-8 sm:grid-cols-2">
              {STEPS.map((step, index) => (
                <li key={step.title} className="flex gap-4">
                  <span
                    aria-hidden="true"
                    className="mt-0.5 font-mono text-sm text-primary"
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="max-w-prose">
                    <h3 className="text-sm font-medium text-foreground">
                      {step.title}
                    </h3>
                    <p className="mt-1.5 text-sm text-muted-foreground">
                      {step.body}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Rates, stated as a table because that is what they are. */}
        <section className="border-b border-border px-4 py-14 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-content">
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              What it costs you
            </h2>
            <p className="mt-2 max-w-prose text-sm text-muted-foreground">
              Nothing, in money. Credits are the unit of fair sharing, granted by
              your administrator so that two GPUs can go round a department. The
              rates below are the defaults; your administrator can change them, and
              your balance always shows the rate in force.
            </p>

            <div className="mt-6 overflow-x-auto rounded-md border border-border bg-card">
              <table className="w-full min-w-[34rem] text-sm">
                <thead>
                  <tr className="border-b border-border text-left">
                    <th className="px-5 py-3 font-medium text-muted-foreground">
                      Workspace
                    </th>
                    <th className="px-5 py-3 font-medium text-muted-foreground">
                      Rate
                    </th>
                    <th className="px-5 py-3 font-medium text-muted-foreground">
                      Hardware
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  <tr>
                    <td className="px-5 py-3.5 font-medium text-foreground">
                      GPU workspace
                    </td>
                    <td className="px-5 py-3.5 font-mono text-foreground">
                      1 credit / minute
                    </td>
                    <td className="px-5 py-3.5 text-muted-foreground">
                      One whole NVIDIA L4, not shared while you hold it
                    </td>
                  </tr>
                  <tr>
                    <td className="px-5 py-3.5 font-medium text-foreground">
                      CPU workspace
                    </td>
                    <td className="px-5 py-3.5 font-mono text-foreground">Free</td>
                    <td className="px-5 py-3.5 text-muted-foreground">
                      The same environment, without a GPU
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* Who it is for. Rows, not three identical cards. */}
        <section className="px-4 py-14 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-content">
            <h2 className="text-xl font-semibold tracking-tight text-foreground">
              Who it is for
            </h2>
            <dl className="mt-8 space-y-6 border-t border-border pt-6">
              {[
                {
                  who: "Students",
                  what: "Course projects and capstones that need more than a laptop. Nothing to install, and your work is still there next week.",
                },
                {
                  who: "Researchers",
                  what: "Experiments in PyTorch on a dedicated L4, with the environment already built and pinned.",
                },
                {
                  who: "Faculty",
                  what: "GPU coursework you can set without asking a class to configure a VPN. Credits are granted per person, and usage is visible per session.",
                },
              ].map(({ who, what }) => (
                <div
                  key={who}
                  className="grid gap-1.5 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-6"
                >
                  <dt className="text-sm font-medium text-foreground">{who}</dt>
                  <dd className="max-w-prose text-sm text-muted-foreground">
                    {what}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        </section>
      </main>

      <footer className="border-t border-border px-4 py-8 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-content flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <Wordmark showSubtitle />
          <a
            href="https://github.com/syedahmedkhaderi/sahab"
            target="_blank"
            rel="noreferrer"
            className="text-xs text-muted-foreground underline decoration-border underline-offset-4 transition-colors hover:text-foreground hover:decoration-current"
          >
            Source and deployment instructions on GitHub
          </a>
        </div>
      </footer>
    </div>
  );
}
