import * as React from "react";
import { cn } from "@/lib/utils";

/** Base shimmer skeleton block. */
function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-md bg-gray-200 dark:bg-gray-700/60", className)}
      {...props}
    />
  );
}

/** One or more lines of text skeleton. */
function SkeletonText({ lines = 1, className }: { lines?: number; className?: string }) {
  return (
    <div className={cn("space-y-2", className)}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className={cn("h-4", i === lines - 1 && lines > 1 ? "w-3/4" : "w-full")}
        />
      ))}
    </div>
  );
}

/** Generic card skeleton. */
function SkeletonCard({ className }: { className?: string }) {
  return (
    <div className={cn("rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4", className)}>
      <SkeletonText />
      <SkeletonText lines={2} />
    </div>
  );
}

/** Circular avatar skeleton. */
function SkeletonAvatar({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const sizeMap = { sm: "h-8 w-8", md: "h-10 w-10", lg: "h-12 w-12" } as const;
  return <Skeleton className={cn("rounded-full shrink-0", sizeMap[size])} />;
}

/** 16:9 video thumbnail skeleton. */
function SkeletonVideo({ className }: { className?: string }) {
  return <Skeleton className={cn("aspect-video w-full rounded-xl", className)} />;
}

/** Full project card skeleton matching the project card layout. */
function SkeletonProjectCard({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-4", className)}>
      <SkeletonVideo />
      <div className="space-y-2">
        <Skeleton className="h-5 w-3/4" />
        <Skeleton className="h-4 w-1/2" />
      </div>
      <div className="flex gap-2">
        <Skeleton className="h-6 w-16 rounded-full" />
        <Skeleton className="h-6 w-16 rounded-full" />
      </div>
    </div>
  );
}

export { Skeleton, SkeletonText, SkeletonCard, SkeletonAvatar, SkeletonVideo, SkeletonProjectCard };
