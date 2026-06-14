"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const Tabs        = TabsPrimitive.Root;
const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn("mt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500", className)}
    {...props}
  />
));
TabsContent.displayName = "TabsContent";

const tabsListVariants = cva(
  "inline-flex items-center justify-start p-1 gap-0.5",
  {
    variants: {
      variant: {
        default:    "rounded-lg bg-gray-100 dark:bg-gray-800 w-full",
        underline:  "bg-transparent border-b border-gray-200 dark:border-gray-700 rounded-none p-0 gap-4 w-full",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

type TabsListProps = React.ComponentPropsWithoutRef<typeof TabsPrimitive.List> &
  VariantProps<typeof tabsListVariants>;

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  TabsListProps
>(({ className, variant, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(tabsListVariants({ variant }), className)}
    data-variant={variant}
    {...props}
  />
));
TabsList.displayName = "TabsList";

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md",
      "px-3 py-1.5 text-sm font-medium",
      "text-gray-600 dark:text-gray-400",
      "transition-all duration-150",
      "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
      "disabled:pointer-events-none disabled:opacity-50",
      // default variant active state
      "data-[state=active]:bg-white dark:data-[state=active]:bg-gray-700",
      "data-[state=active]:text-gray-900 dark:data-[state=active]:text-white",
      "data-[state=active]:shadow-sm",
      // underline variant — parent sets data-variant
      "[[data-variant=underline]_&]:bg-transparent [[data-variant=underline]_&]:rounded-none",
      "[[data-variant=underline]_&]:border-b-2 [[data-variant=underline]_&]:border-transparent",
      "[[data-variant=underline]_&]:pb-2",
      "[[data-variant=underline]_&[data-state=active]]:border-blue-600",
      "[[data-variant=underline]_&[data-state=active]]:text-blue-600 dark:[[data-variant=underline]_&[data-state=active]]:text-blue-400",
      "[[data-variant=underline]_&[data-state=active]]:shadow-none [[data-variant=underline]_&[data-state=active]]:bg-transparent",
      className
    )}
    {...props}
  />
));
TabsTrigger.displayName = "TabsTrigger";

export { Tabs, TabsList, TabsTrigger, TabsContent };
