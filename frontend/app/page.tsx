import React from "react";
import Link from "next/link";
import {
  Server,
  Cpu,
  GraduationCap,
  FlaskConical,
  BookOpen,
  Shield,
  Zap,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const siteName = process.env.NEXT_PUBLIC_SITE_NAME ?? "Sahab";

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
          <div className="flex items-center gap-2">
            <Server className="h-6 w-6 text-primary" />
            <span className="text-lg font-bold tracking-tight">{siteName}</span>
          </div>
          <div className="flex items-center gap-2">
            <Link href="/login">
              <Button variant="ghost" size="sm">
                Sign in
              </Button>
            </Link>
            <Link href="/signup">
              <Button size="sm">Get started</Button>
            </Link>
          </div>
        </div>
      </header>

      <main className="flex-1">
        {/* Hero */}
        <section className="px-4 py-20 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-4xl text-center">
            <Badge variant="secondary" className="mb-6">
              University GPU Compute Platform
            </Badge>
            <h1 className="mb-6 text-4xl font-bold tracking-tight sm:text-5xl lg:text-6xl">
              GPU compute in your browser.
              <br />
              <span className="text-primary">No VPN. No SSH. No setup.</span>
            </h1>
            <p className="mb-10 text-lg text-muted-foreground sm:text-xl">
              {siteName} gives students and researchers access to university GPU servers through a
              professional browser-based IDE. Open a notebook or VS Code, run your models, and
              pay only for the compute time you use.
            </p>
            <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
              <Link href="/signup">
                <Button size="lg" className="w-full sm:w-auto">
                  Request access
                </Button>
              </Link>
              <Link href="/login">
                <Button variant="outline" size="lg" className="w-full sm:w-auto">
                  Sign in
                </Button>
              </Link>
            </div>
          </div>
        </section>

        {/* Who it's for */}
        <section className="border-t border-border bg-muted/30 px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <h2 className="mb-12 text-center text-2xl font-bold sm:text-3xl">
              Built for the university community
            </h2>
            <div className="grid gap-6 sm:grid-cols-3">
              {[
                {
                  icon: GraduationCap,
                  title: "Students",
                  description:
                    "Train your course projects and hackathon models on real GPU hardware — no local setup, no waiting for shared lab computers. Your files persist between sessions.",
                },
                {
                  icon: FlaskConical,
                  title: "Researchers",
                  description:
                    "Run experiments with PyTorch, TensorFlow, or JAX on a dedicated NVIDIA L4. Get a full notebook environment plus VS Code in the browser, with your code and data intact.",
                },
                {
                  icon: BookOpen,
                  title: "Professors",
                  description:
                    "Assign GPU-enabled coursework without asking students to configure VPN or SSH. Grant course credits, monitor usage, and ensure fair access across your cohort.",
                },
              ].map(({ icon: Icon, title, description }) => (
                <Card key={title}>
                  <CardHeader>
                    <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                      <Icon className="h-5 w-5" />
                    </div>
                    <CardTitle className="text-xl">{title}</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <p className="text-muted-foreground">{description}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section className="px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-3xl">
            <h2 className="mb-12 text-center text-2xl font-bold sm:text-3xl">
              From login to working GPU in under 60 seconds
            </h2>
            <ol className="space-y-6">
              {[
                "Sign in with your university email address.",
                'Click "Launch Workspace," pick a runtime (GPU or CPU) and an environment.',
                "Your container starts — JupyterLab and VS Code are ready in the browser.",
                "Work normally. Credits are deducted per minute of GPU time.",
                "Stop your session when done. Your files are saved for next time.",
              ].map((step, i) => (
                <li key={i} className="flex items-start gap-4">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
                    {i + 1}
                  </span>
                  <p className="pt-1 text-base text-muted-foreground">{step}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* Pricing */}
        <section className="border-t border-border bg-muted/30 px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <h2 className="mb-4 text-center text-2xl font-bold sm:text-3xl">
              Simple credit-based pricing
            </h2>
            <p className="mb-12 text-center text-muted-foreground">
              Credits are granted by your administrator. There is no credit card required.
            </p>
            <div className="mx-auto grid max-w-2xl gap-6 sm:grid-cols-2">
              <Card>
                <CardHeader>
                  <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-violet-100 text-violet-700">
                    <Server className="h-5 w-5" />
                  </div>
                  <CardTitle>GPU Session</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="text-3xl font-bold">
                    60 <span className="text-base font-normal text-muted-foreground">credits / hour</span>
                  </p>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    <li>NVIDIA L4 — 24 GB VRAM</li>
                    <li>Dedicated whole-GPU allocation</li>
                    <li>JupyterLab + VS Code</li>
                    <li>Persistent 50 GB workspace</li>
                  </ul>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-blue-100 text-blue-700">
                    <Cpu className="h-5 w-5" />
                  </div>
                  <CardTitle>CPU Session</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <p className="text-3xl font-bold">
                    Free <span className="text-base font-normal text-muted-foreground"></span>
                  </p>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    <li>Standard CPU compute</li>
                    <li>No GPU access</li>
                    <li>JupyterLab + VS Code</li>
                    <li>Persistent 50 GB workspace</li>
                  </ul>
                </CardContent>
              </Card>
            </div>
            <p className="mt-6 text-center text-xs text-muted-foreground">
              Exact rates are set by the platform administrator and may vary.
            </p>
          </div>
        </section>

        {/* Feature highlights */}
        <section className="px-4 py-16 sm:px-6 lg:px-8">
          <div className="mx-auto max-w-7xl">
            <div className="grid gap-8 sm:grid-cols-3">
              {[
                {
                  icon: Shield,
                  title: "Isolated workspaces",
                  body: "Each session runs in a dedicated container with exactly one GPU pinned. Your code and VRAM are never shared with other users.",
                },
                {
                  icon: Zap,
                  title: "Pre-built ML stacks",
                  body: "PyTorch, CUDA, transformers, and data-science libraries are pre-installed and version-pinned. No environment setup needed.",
                },
                {
                  icon: Clock,
                  title: "Fair scheduling",
                  body: "When both GPUs are busy, you join a queue and are notified when one is free. Idle sessions are culled automatically so GPUs stay available.",
                },
              ].map(({ icon: Icon, title, body }) => (
                <div key={title} className="flex gap-4">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" />
                  </div>
                  <div>
                    <h3 className="mb-1 font-semibold">{title}</h3>
                    <p className="text-sm text-muted-foreground">{body}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-border px-4 py-8 sm:px-6 lg:px-8">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Server className="h-4 w-4" />
            <span className="text-sm">{siteName}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            University GPU Compute Platform
          </p>
        </div>
      </footer>
    </div>
  );
}
