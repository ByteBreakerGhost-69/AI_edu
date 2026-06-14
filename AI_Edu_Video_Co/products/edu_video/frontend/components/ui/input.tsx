import * as React from "react";
import { cn } from "@/lib/utils";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  /** Render error styling (red border + ring) */
  error?:      boolean;
  /** Icon rendered inside the left edge */
  leftIcon?:   React.ReactNode;
  /** Icon rendered inside the right edge */
  rightIcon?:  React.ReactNode;
};

/** Single-line text input with icon and error state support. */
const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, error, leftIcon, rightIcon, type, ...props }, ref) => (
    <div className="relative w-full">
      {leftIcon && (
        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
          {leftIcon}
        </span>
      )}
      <input
        type={type}
        ref={ref}
        className={cn(
          "flex h-10 w-full rounded-md",
          "border border-gray-300 dark:border-gray-600",
          "bg-white dark:bg-gray-800",
          "px-3 py-2 text-sm",
          "text-gray-900 dark:text-gray-100",
          "placeholder:text-gray-400 dark:placeholder:text-gray-500",
          "focus-visible:outline-none focus-visible:ring-2",
          "focus-visible:ring-blue-500 focus-visible:border-transparent",
          "disabled:cursor-not-allowed disabled:opacity-50",
          "transition-colors duration-150",
          "file:border-0 file:bg-transparent file:text-sm file:font-medium",
          leftIcon  && "pl-10",
          rightIcon && "pr-10",
          error && "border-red-500 dark:border-red-500 focus-visible:ring-red-500",
          className
        )}
        {...props}
      />
      {rightIcon && (
        <span className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none">
          {rightIcon}
        </span>
      )}
    </div>
  )
);
Input.displayName = "Input";

export { Input };
