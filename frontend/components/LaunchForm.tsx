"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Cpu, Server, AlertCircle, Users } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { sessions as sessionsApi, images as imagesApi, rates as ratesApi } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type { Image, Rate } from "@/lib/types";
import { cn } from "@/lib/utils";

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
  const [allGpusBusy, setAllGpusBusy] = useState(false);
  const [fallbackCpu, setFallbackCpu] = useState(false);

  useEffect(() => {
    Promise.all([imagesApi.list(), ratesApi.list()])
      .then(([imgs, rs]) => {
        setAvailableImages(imgs.filter((i) => i.enabled));
        setAvailableRates(rs);
        const defaultImg = imgs.find((i) => i.is_default && i.enabled) ?? imgs.find((i) => i.enabled);
        if (defaultImg) setSelectedImageId(defaultImg.id);
      })
      .catch(() => setError("Failed to load catalog data."))
      .finally(() => setLoadingData(false));
  }, []);

  const rateFor = (type: ResourceType): number => {
    const r = availableRates.find((r) => r.resource_type === type);
    return r ? r.credits_per_minute * 60 : 0;
  };

  const filteredImages = availableImages.filter((img) =>
    selectedResource === "l4_gpu" ? img.kind === "gpu" : img.kind === "cpu"
  );

  // When resource type changes, reset selected image to first valid
  useEffect(() => {
    const first = filteredImages[0];
    if (first) setSelectedImageId(first.id);
    else setSelectedImageId("");
  }, [selectedResource]); // eslint-disable-line react-hooks/exhaustive-deps

  const creditsPerHour = rateFor(selectedResource);
  const hasEnoughCredits = balance >= creditsPerHour / 60; // at least 1 minute
  const noImages = filteredImages.length === 0;

  const handleSubmit = async () => {
    if (!selectedImageId) return;
    setLoading(true);
    setError(null);
    setAllGpusBusy(false);

    try {
      const session = await sessionsApi.create({
        resource_type: selectedResource,
        image_id: selectedImageId,
        fallback_cpu: fallbackCpu,
      });

      // Poll until running or queued visible then redirect
      router.push(`/sessions/${session.id}/connect`);
    } catch (e) {
      if (e instanceof ApiClientError) {
        if (e.status === 409 || e.detail.toLowerCase().includes("busy") || e.detail.toLowerCase().includes("gpu")) {
          setAllGpusBusy(true);
        } else if (e.status === 402 || e.detail.toLowerCase().includes("credit")) {
          setError("Insufficient credits to start a session. Please request a top-up.");
        } else {
          setError(e.detail);
        }
      } else {
        setError("An unexpected error occurred. Please try again.");
      }
      setLoading(false);
    }
  };

  if (loadingData) {
    return (
      <div className="flex h-32 items-center justify-center text-muted-foreground">
        Loading catalog...
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Runtime selector */}
      <div>
        <p className="mb-3 text-sm font-medium">Runtime</p>
        <div className="grid gap-3 sm:grid-cols-2">
          {(["l4_gpu", "cpu"] as ResourceType[]).map((type) => {
            const rate = rateFor(type);
            const isGpu = type === "l4_gpu";
            return (
              <button
                key={type}
                onClick={() => setSelectedResource(type)}
                className={cn(
                  "flex items-start gap-3 rounded-lg border p-4 text-left transition-colors",
                  selectedResource === type
                    ? "border-primary bg-primary/5 ring-2 ring-primary"
                    : "border-border hover:bg-accent"
                )}
              >
                <div className={cn("mt-0.5 rounded-md p-1.5", isGpu ? "bg-violet-100 text-violet-700" : "bg-blue-100 text-blue-700")}>
                  {isGpu ? <Server className="h-5 w-5" /> : <Cpu className="h-5 w-5" />}
                </div>
                <div>
                  <p className="font-semibold">{isGpu ? "GPU Session" : "CPU Session"}</p>
                  <p className="text-sm text-muted-foreground">
                    {isGpu ? "NVIDIA L4 — 24 GB VRAM" : "Standard CPU — no GPU"}
                  </p>
                  <p className="mt-1 text-sm font-medium">
                    {rate > 0
                      ? `${rate.toFixed(0)} credits / hour`
                      : "Free"}
                  </p>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* Image selector */}
      <div>
        <p className="mb-3 text-sm font-medium">Environment</p>
        {noImages ? (
          <div className="rounded-lg border border-border px-4 py-8 text-center text-sm text-muted-foreground">
            No environments available for the selected runtime.
          </div>
        ) : (
          <div className="grid gap-2">
            {filteredImages.map((img) => (
              <button
                key={img.id}
                onClick={() => setSelectedImageId(img.id)}
                className={cn(
                  "flex items-center justify-between rounded-md border px-4 py-3 text-left text-sm transition-colors",
                  selectedImageId === img.id
                    ? "border-primary bg-primary/5 ring-2 ring-primary"
                    : "border-border hover:bg-accent"
                )}
              >
                <span className="font-medium">{img.name}</span>
                {img.is_default && (
                  <span className="text-xs text-muted-foreground">Default</span>
                )}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* All GPUs busy — fallback options */}
      {allGpusBusy && selectedResource === "l4_gpu" && (
        <Alert variant="warning">
          <Users className="h-4 w-4" />
          <AlertTitle>All GPUs are currently in use</AlertTitle>
          <AlertDescription className="mt-2 space-y-3">
            <p>Both NVIDIA L4 GPUs are occupied. You can:</p>
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setFallbackCpu(false);
                  setAllGpusBusy(false);
                  // re-submit with queue option — the backend will queue it
                  handleSubmit();
                }}
                disabled={loading}
              >
                Join the GPU queue
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setSelectedResource("cpu");
                  setAllGpusBusy(false);
                }}
              >
                Switch to CPU session (free)
              </Button>
            </div>
          </AlertDescription>
        </Alert>
      )}

      {/* Insufficient credits */}
      {!hasEnoughCredits && creditsPerHour > 0 && !allGpusBusy && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Insufficient credits</AlertTitle>
          <AlertDescription>
            You need at least {Math.ceil(creditsPerHour / 60)} credit to start a{" "}
            {selectedResource === "l4_gpu" ? "GPU" : "CPU"} session.{" "}
            <a href="/billing" className="underline">
              Request a top-up
            </a>
            .
          </AlertDescription>
        </Alert>
      )}

      {error && !allGpusBusy && (
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Submit */}
      <Button
        className="w-full"
        size="lg"
        disabled={
          loading ||
          noImages ||
          !selectedImageId ||
          (!hasEnoughCredits && creditsPerHour > 0) ||
          allGpusBusy
        }
        onClick={handleSubmit}
      >
        {loading ? "Launching..." : "Launch Workspace"}
      </Button>
    </div>
  );
}
