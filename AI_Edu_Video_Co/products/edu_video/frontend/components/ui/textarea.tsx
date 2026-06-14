import * as React from "react";
import { cn } from "@/lib/utils";

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  /** Render error styling */
  error?:         boolean;
  /** Show character count below the textarea */
  showCharCount?: boolean;
};

/** Multi-line text input with character count support. */
const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, error, showCharCount, maxLength, value, defaultValue, onChange, ...props }, ref) => {
    const [charCount, setCharCount] = React.useState(() => {
      const initial = value ?? defaultValue ?? "";
      return String(initial).length;
    });

    const handleChange = React.useCallback(
      (e: React.ChangeEvent<HTMLTextAreaElement>) => {
        setCharCount(e.target.value.length);
        onChange?.(e);
      },
      [onChange]
    );

    const nearLimit  = maxLength && charCount >= maxLength * 0.9;
    const overLimit  = maxLength && charCount > maxLength;

    return (
      <div className="w-full">
        <textarea
          ref={ref}
          maxLength={maxLength}
          value={value}
          defaultValue={defaultValue}
          onChange={handleChange}
          className={cn(
            "min-h-[80px] w-full rounded-md resize-none",
            "border border-gray-300 dark:border-gray-600",
            "bg-white dark:bg-gray-800",
            "px-3 py-2 text-sm",
            "text-gray-900 dark:text-gray-100",
            "placeholder:text-gray-400 dark:placeholder:text-gray-500",
            "focus-visible:outline-none focus-visible:ring-2",
            "focus-visible:ring-blue-500 focus-visible:border-transparent",
            "disabled:cursor-not-allowed disabled:opacity-50",
            "transition-colors duration-150",
            error && "border-red-500 dark:border-red-500 focus-visible:ring-red-500",
            className
          )}
          {...props}
        />
        {showCharCount && maxLength && (
          <div className="flex justify-end mt-1">
            <span
              className={cn(
                "text-xs",
                overLimit  ? "text-red-500"   :
                nearLimit  ? "text-amber-500" :
                             "text-gray-400"
              )}
            >
              {charCount} / {maxLength}
            </span>
          </div>
        )}
      </div>
    );
  }
);
Textarea.displayName = "Textarea";

export { Textarea };
