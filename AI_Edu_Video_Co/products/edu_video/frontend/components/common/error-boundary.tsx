"use client";

import * as React from "react";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";

// -------------------------------------------------------------------------- //
// Types                                                                        //
// -------------------------------------------------------------------------- //

type Level = "page" | "section" | "component";

export type ErrorBoundaryProps = {
  children:           React.ReactNode;
  fallback?:          React.ReactNode;
  onError?:           (error: Error, info: React.ErrorInfo) => void;
  /** Auto-reset when this value changes (pass router pathname). */
  pathname?:          string;
  level?:             Level;
};

type State = {
  hasError:  boolean;
  error:     Error | null;
  errorInfo: React.ErrorInfo | null;
};

// -------------------------------------------------------------------------- //
// Default fallback UIs                                                         //
// -------------------------------------------------------------------------- //

function PageFallback({ error, onReset }: { error: Error | null; onReset: () => void }) {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4">
      <AlertCircle className="h-12 w-12 text-red-400 mb-4" aria-hidden />
      <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
        Something went wrong
      </h2>
      <p className="mt-2 text-sm text-gray-500 dark:text-gray-400 max-w-md text-center">
        An unexpected error occurred. You can try again or return to the dashboard.
      </p>
      <div className="mt-6 flex gap-3">
        <Button onClick={onReset}>Try again</Button>
        <Button variant="outline" onClick={() => { window.location.href = ROUTES.dashboard; }}>
          Go home
        </Button>
      </div>
      {process.env.NODE_ENV === "development" && error && (
        <pre className="mt-6 max-h-32 overflow-auto rounded bg-gray-100 dark:bg-gray-800 p-3 text-xs font-mono text-left w-full max-w-xl">
          {error.message}
        </pre>
      )}
    </div>
  );
}

function SectionFallback({ error, onReset }: { error: Error | null; onReset: () => void }) {
  return (
    <div className="p-8 rounded-xl border border-red-200 dark:border-red-900/30 bg-red-50 dark:bg-red-900/10 flex flex-col items-center text-center">
      <AlertCircle className="h-8 w-8 text-red-400 mb-3" aria-hidden />
      <p className="text-sm font-medium text-red-700 dark:text-red-300 mb-3">
        This section failed to load
      </p>
      <Button size="sm" onClick={onReset}>Try again</Button>
      {process.env.NODE_ENV === "development" && error && (
        <pre className="mt-4 max-h-24 overflow-auto rounded bg-white/60 dark:bg-gray-900/60 p-2 text-xs font-mono text-left w-full">
          {error.message}
        </pre>
      )}
    </div>
  );
}

function ComponentFallback({ onReset }: { onReset: () => void }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-red-500">
      <AlertCircle className="h-4 w-4 shrink-0" aria-hidden />
      Failed to load.{" "}
      <button onClick={onReset} className="underline hover:no-underline focus:outline-none">
        Retry
      </button>
    </span>
  );
}

// -------------------------------------------------------------------------- //
// ErrorBoundary class                                                          //
// -------------------------------------------------------------------------- //

/**
 * React error boundary for catching render errors.
 * Pass `pathname` prop to auto-reset on route changes.
 */
export class ErrorBoundary extends React.Component<ErrorBoundaryProps, State> {
  static displayName = "ErrorBoundary";

  state: State = { hasError: false, error: null, errorInfo: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    this.setState({ errorInfo: info });
    this.props.onError?.(error, info);
    if (process.env.NODE_ENV === "development") {
      console.error("[ErrorBoundary]", error, info);
    }
  }

  componentDidUpdate(prevProps: ErrorBoundaryProps) {
    if (
      this.state.hasError &&
      prevProps.pathname !== this.props.pathname
    ) {
      this.reset();
    }
  }

  reset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    if (this.props.fallback) return this.props.fallback;

    const level = this.props.level ?? "page";
    if (level === "section")   return <SectionFallback   error={this.state.error} onReset={this.reset} />;
    if (level === "component") return <ComponentFallback onReset={this.reset} />;
    return <PageFallback error={this.state.error} onReset={this.reset} />;
  }
}

// -------------------------------------------------------------------------- //
// HOC                                                                          //
// -------------------------------------------------------------------------- //

/**
 * Wrap a component with an ErrorBoundary.
 *
 * @example
 *   const SafeChart = withErrorBoundary(Chart, { level: "section" });
 */
export function withErrorBoundary<P extends object>(
  Component: React.ComponentType<P>,
  options?: Omit<ErrorBoundaryProps, "children">
): React.FC<P> {
  const Wrapped: React.FC<P> = (props) => (
    <ErrorBoundary {...options}>
      <Component {...props} />
    </ErrorBoundary>
  );
  Wrapped.displayName = `WithErrorBoundary(${Component.displayName ?? Component.name})`;
  return Wrapped;
  }
