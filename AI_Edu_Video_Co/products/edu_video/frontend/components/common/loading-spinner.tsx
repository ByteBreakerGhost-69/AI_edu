"use client";

import * as React from "react";
import { Loader2, Clock, Cpu, Film, Eye } from "lucide-react";
import { cn } from "@/lib/utils";
import { Progress } from "@/components/ui/progress";

// -------------------------------------------------------------------------- //
// Spinner                                                                      //
// -------------------------------------------------------------------------- //

const SIZES = {
  xs: "h-3 w-3",
  sm: "h-4 w-4",
  md: "h-6 w-6",
  lg: "h-8 w-8",
  xl: "h-12 w-12",
} as const;

const COLORS = {
  default: "text-blue-600 dark:text-blue-400",
  white:   "text-white",
  blue:    "text-blue-500",
  gray:    "text-gray-400",
} as const;

export type SpinnerProps = {
  size?:      keyof typeof SIZES;
  color?:     keyof typeof COLORS;
  className?: string;
};

/** Inline animated loading indicator. */
export function Spinner({ size = "md", color = "default", className }: SpinnerProps) {
  return (
    <Loader2
      className={cn("animate-spin", SIZES[size], COLORS[color], className)}
      aria-hidden
    />
  );
}

// -------------------------------------------------------------------------- //
// PageLoader                                                                   //
// -------------------------------------------------------------------------- //

export function PageLoader({
  message    = "Loading…",
  subMessage,
}: {
  message?:    string;
  subMessage?: string;
}) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-white dark:bg-gray-950">
      <Spinner size="xl" color="blue" />
      <p className="mt-4 text-lg font-medium text-gray-700 dark:text-gray-300">{message}</p>
      {subMessage && (
        <p className="mt-1 text-sm text-gray-400">{subMessage}</p>
      )}
    </div>
  );
}

// -------------------------------------------------------------------------- //
// SectionLoader                                                                //
// -------------------------------------------------------------------------- //

export function SectionLoader({
  height  = "h-64",
  message,
}: {
  height?:  string;
  message?: string;
}) {
  return (
    <div className={cn("flex flex-col items-center justify-center", height)}>
      <Spinner size="lg" />
      {message && (
        <p className="mt-3 text-sm text-gray-400">{message}</p>
      )}
    </div>
  );
}

// -------------------------------------------------------------------------- //
// InlineLoader                                                                 //
// -------------------------------------------------------------------------- //

export function InlineLoader({
  message,
  size = "sm",
}: {
  message?: string;
  size?:    "sm" | "md";
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <Spinner size={size} />
      {message && (
        <span className="text-sm text-gray-500">{message}</span>
      )}
    </span>
  );
}

// -------------------------------------------------------------------------- //
// VideoProcessingLoader                                                        //
// -------------------------------------------------------------------------- //

const STAGE_CONFIG = {
  queued: {
    Icon:    Clock,
    color:   "text-amber-500",
    animate: "animate-pulse",
    label:   "Waiting in queue…",
  },
  orchestrating: {
    Icon:    Cpu,
    color:   "text-blue-500",
    animate: "animate-bounce",
    label:   "Generating your script…",
  },
  rendering: {
    Icon:    Film,
    color:   "text-purple-500",
    animate: "animate-spin",
    label:   "Rendering your video…",
  },
  review: {
    Icon:    Eye,
    color:   "text-green-500",
    animate: "animate-pulse",
    label:   "Under expert review…",
  },
} as const;

export function VideoProcessingLoader({
  stage,
  percent,
  message,
}: {
  stage:    keyof typeof STAGE_CONFIG;
  percent?: number;
  message?: string;
}) {
  const { Icon, color, animate, label } = STAGE_CONFIG[stage];

  return (
    <div className="w-full max-w-sm mx-auto p-8 text-center">
      <Icon
        className={cn(
          "mx-auto h-12 w-12",
          color,
          animate,
          stage === "rendering" && "[animation-duration:3000ms]"
        )}
        aria-hidden
      />
      <p className="mt-4 text-base font-medium text-gray-700 dark:text-gray-200">
        {message ?? label}
      </p>
      {percent !== undefined && (
        <div className="mt-6">
          <Progress value={percent} variant="default" size="sm" animated />
          <p className="mt-1 text-right text-xs text-gray-400">{Math.round(percent)}%</p>
        </div>
      )}
    </div>
  );
          }
