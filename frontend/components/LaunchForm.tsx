"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { AlertCircle, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Skeleton } from "@/components/ui/skeleton";
import { sessions as sessionsApi, images as imagesApi, rates as ratesApi } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type { Image, Rate } from "@/lib/types";
import { cn, formatCredits, creditsWithUnit } from "@/lib/utils";

interface LaunchFormProps {
  balance: number;
}

type ResourceType = "l4_gpu" | "cpu";

export function LaunchForm({ balance }: LaunchFormProps) {
  const router = useRouter();

  const [availableImages, setAvailableImages] = useState<Image[]>([]);
  const [availableRates, setAvailableRates] = useState<Rate[]>([]);
  const [selectedResource, setSelectedResource] = useState<ResourceType>("l4_gpu");
  const [selectedImageId, setSelectedImageId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [loadingData, setLoadingData] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The message the API sent when every free GPU turned out to be busy. Held
  // separately from `error` because it comes with choices, not just a warning.
  const [gpusBusy, setGpusBusy] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([imagesApi.list(), ratesApi.list()])
      .then(([imgs, rs]) => {
        setAvailableImages(imgs.filter((i) => i.enabled));
        setAvailableRates(rs);
      })
      .catch(() =>
        setError("Could not load the list of environments. Reload the page to try again.")
      )
      .finally(() => setLoadingData(false));
  }, []);

  const ratePerMinute = (type: ResourceType): number =>
    availableRates.find((r) => r.resource_type === type)?.credits_per_minute ?? 0;

  const filteredImages = availableImages.filter((img) =>
    selectedResource === "l4_gpu" ? img.kind === "gpu" : img.kind === "cpu"
  );

  // Keep the selected image valid for the chosen runtime, so a GPU session can
  // never be left pointing at a CPU image (or the reverse).
  useEffect(() => {
    const valid = availableImages.filter((img) =>
      selectedResource === "l4_gpu" ? img.kind === "gpu" : img.kind === "cpu"
    );
    const preferred = valid.find((i) => i.is_default) ?? valid[0];
    setSelectedImageId(preferred ? preferred.id : "");
  }, [selectedResource, availableImages]);

  const rate = ratePerMinute(selectedResource);
  const hasEnoughCredits = rate <= 0 || balance >= rate;
  const noImages = filteredImages.length === 0;

  const launch = async (options?: { queueIfBusy?: boolean }) => {
    if (!selectedImageId) return;
    setLoading(true);
    setError(null);
    if (!options?.queueIfBusy) setGpusBusy(null);

    try {
      const session = await sessionsApi.create({
        resource_type: selectedResource,
        image_id: selectedImageId,
        queue_if_busy: options?.queueIfBusy ?? false,
      });
      router.push(`/sessions/${session.id}/connect`);
    } catch (e) {
      if (e instanceof ApiClientError) {
        if (e.status === 409) {
          // The API's own words: it knows whether the pool is empty or busy.
          setGpusBusy(e.detail);
        } else {
          setError(e.detail);
        }
      } else {
        setError("Something went wrong starting your workspace. Please try again.");
      }
      setLoading(false);
    }
  };

  if (loadingData) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-9 w-full" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <fieldset>
        <legend className="text-sm font-medium text-foreground">Hardware</legend>
        <p className="mt-1 text-sm text-muted-foreground">
          You do not pick a specific GPU — Sahab assigns one that is free.
        </p>

        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {(["l4_gpu", "cpu"] as ResourceType[]).map((type) => {
            const perMinute = ratePerMinute(type);
            const isGpu = type === "l4_gpu";
            const selected = selectedResource === type;
            return (
              <button
                key={type}
                type="button"
                aria-pressed={selected}
                onClick={() => setSelectedResource(type)}
                className={cn(
                  "flex items-start justify-between gap-3 rounded-md border p-4 text-left transition-colors",
                  selected
                    ? "border-primary bg-info-subtle"
                    : "border-border bg-card hover:border-border-strong"
                )}
              >
                <span className="space-y-1">
                  <span className="block text-sm font-medium text-foreground">
                    {isGpu ? "GPU workspace" : "CPU workspace"}
                  </span>
                  <span className="block font-mono text-xs text-muted-foreground">
                    {isGpu ? "NVIDIA L4 · 24 GB" : "No GPU"}
                  </span>
                  <span className="block text-sm text-foreground">
                    {perMinute > 0 ? `${creditsWithUnit(perMinute)} / minute` : "Free"}
                  </span>
                </span>
                {selected && (
                  <Check
                    className="mt-0.5 h-4 w-4 shrink-0 text-primary"
                    aria-hidden="true"
                  />
                )}
              </button>
            );
          })}
        </div>
      </fieldset>

      <fieldset>
        <legend className="text-sm font-medium text-foreground">Environment</legend>
        <p className="mt-1 text-sm text-muted-foreground">
          The container image your workspace runs. Libraries are pre-installed and
          version-pinned.
        </p>

        {noImages ? (
          <p className="mt-3 rounded-md border border-dashed border-border-strong px-4 py-6 text-sm text-muted-foreground">
            No environment is available for this hardware yet. An administrator
            needs to enable one.
          </p>
        ) : (
          <div className="mt-3 grid gap-2">
            {filteredImages.map((img) => {
              const selected = selectedImageId === img.id;
              return (
                <button
                  key={img.id}
                  type="button"
                  aria-pressed={selected}
                  onClick={() => setSelectedImageId(img.id)}
                  className={cn(
                    "flex items-center justify-between gap-3 rounded-md border px-4 py-3 text-left transition-colors",
                    selected
                      ? "border-primary bg-info-subtle"
                      : "border-border bg-card hover:border-border-strong"
                  )}
                >
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {img.name}
                    </span>
                    {img.is_default && (
                      <span className="block text-xs text-muted-foreground">
                        Recommended
                      </span>
                    )}
                  </span>
                  {selected && (
                    <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                  )}
                </button>
              );
            })}
          </div>
        )}
      </fieldset>

      {/* No GPU available. The API distinguishes an empty pool from GPUs that
          are busy with outside work, so its wording is shown rather than a
          guess, and each choice below actually does something. */}
      {gpusBusy && selectedResource === "l4_gpu" && (
        <Alert variant="warning">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>No GPU right now</AlertTitle>
          <AlertDescription className="mt-1.5 space-y-3">
            <p>{gpusBusy}</p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                size="sm"
                onClick={() => {
                  setSelectedResource("cpu");
                  setGpusBusy(null);
                }}
              >
                Start a CPU workspace instead
              </Button>
              <Button
                size="sm"
                variant="outline"
                loading={loading}
                onClick={() => launch({ queueIfBusy: true })}
              >
                Wait for a GPU
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {!hasEnoughCredits && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Not enough credits</AlertTitle>
          <AlertDescription>
            A GPU workspace costs {creditsWithUnit(rate)} per minute and your
            balance is {formatCredits(balance)}. A CPU workspace is free, or{" "}
            <Link href="/billing" className="underline underline-offset-4">
              ask an administrator for more credits
            </Link>
            .
          </AlertDescription>
        </Alert>
      )}

      {error && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" aria-hidden="true" />
          <AlertTitle>Could not start your workspace</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <div className="space-y-2">
        <Button
          className="w-full"
          size="lg"
          loading={loading}
          disabled={noImages || !selectedImageId || !hasEnoughCredits}
          onClick={() => launch()}
        >
          {loading
            ? "Starting your workspace"
            : selectedResource === "l4_gpu"
              ? "Start GPU workspace"
              : "Start CPU workspace"}
        </Button>
        <p className="text-center text-xs text-muted-foreground">
          {selectedResource === "l4_gpu"
            ? "Credits are charged per minute from the moment it starts running."
            : "A CPU workspace does not use credits."}
        </p>
      </div>
    </div>
  );
}
