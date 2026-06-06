/**
 * subscription.ts
 * Billing and subscription types — maps to backend models/subscription.py,
 * billing/tier_config.py, billing/usage_limiter.py, and billing/invoice_service.py.
 */

// -------------------------------------------------------------------------- //
// Tier definitions                                                              //
// -------------------------------------------------------------------------- //

/**
 * Available subscription tiers.
 * Maps to backend tier field in Subscription model.
 */
export const TIERS = {
  FREE:    "free",
  PREMIUM: "premium",
} as const;

export type Tier = (typeof TIERS)[keyof typeof TIERS];

/**
 * Subscription lifecycle status.
 * Maps to backend Subscription.status field.
 */
export type SubscriptionStatus =
  | "active"      // In good standing
  | "trialing"    // In free trial period
  | "past_due"    // Payment failed — grace period active
  | "cancelled"   // Cancelled — access until period end
  | "incomplete"; // Stripe subscription incomplete (payment pending)

/**
 * Features available per tier.
 * Maps to backend TierFeatures in billing/tier_config.py.
 */
export type TierFeatures = {
  readonly tier: Tier;
  readonly videosPerMonth: number;
  readonly maxScenesPerVideo: number;
  readonly allowedSubjects: readonly string[];
  readonly allowedCurricula: readonly string[];
  readonly allowedLanguages: readonly string[];
  readonly allowedDifficultyLevels: readonly string[];
  readonly priorityQueue: boolean;
  readonly humanReview: boolean;
  readonly watermark: boolean;
  readonly subtitleDownload: boolean;
  readonly apiAccess: boolean;
  readonly storageRetentionDays: number;
  readonly maxVideoDurationSeconds: number;
  readonly monthlyCostUsd: number;          // USD; 0.0 for free tier
};

/**
 * Result of a feature gate check.
 * Maps to backend FeatureGateResult in billing/tier_config.py.
 */
export type FeatureGateResult = {
  readonly allowed: boolean;
  readonly reason: string | null;           // Why denied; null if allowed
  readonly upgradeRequired: boolean;        // True if premium would grant access
  readonly suggestedTier: Tier | null;      // "premium" if upgradeRequired
};

// -------------------------------------------------------------------------- //
// Subscription record                                                           //
// -------------------------------------------------------------------------- //

/**
 * User subscription record.
 * Maps to backend Subscription model in models/subscription.py
 * + SubscriptionResponse in billing/subscription_service.py.
 */
export type Subscription = {
  readonly subscriptionId: string;          // UUID
  readonly userId: string;                  // UUID
  readonly tier: Tier;
  readonly status: SubscriptionStatus;
  readonly stripeSubscriptionId: string | null; // null for free tier
  readonly currentPeriodStart: string | null;   // ISO 8601
  readonly currentPeriodEnd: string | null;     // ISO 8601
  readonly cancelAtPeriodEnd: boolean;
  readonly videosUsed: number;              // Used this billing period
  readonly videosLimit: number;             // Monthly limit for this tier
  readonly trialEnd: string | null;         // ISO 8601; null if no trial
  readonly features: TierFeatures;
};

// -------------------------------------------------------------------------- //
// Quota types                                                                   //
// -------------------------------------------------------------------------- //

/**
 * Current quota status for a user.
 * Maps to backend QuotaStatus in billing/usage_limiter.py.
 */
export type QuotaStatus = {
  readonly userId: string;
  readonly tier: Tier;
  readonly videosUsed: number;
  readonly videosLimit: number;
  readonly videosRemaining: number;
  readonly resetsAt: string;               // ISO 8601 — next billing period start
  readonly isExceeded: boolean;
  readonly percentageUsed: number;         // 0.0–100.0
};

// -------------------------------------------------------------------------- //
// Invoice types                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Invoice payment status.
 */
export type InvoiceStatus = "paid" | "open" | "void" | "uncollectible";

/**
 * Invoice summary for list display.
 * Maps to backend InvoiceSummary in models/invoice.py.
 */
export type InvoiceSummary = {
  readonly id: string;                      // UUID
  readonly stripeInvoiceId: string;
  readonly amountUsd: number;               // USD float
  readonly currency: string;                // e.g. "usd"
  readonly status: InvoiceStatus;
  readonly description: string;
  readonly invoicePdfUrl: string | null;    // Stripe-hosted PDF URL
  readonly hostedInvoiceUrl: string | null; // Stripe-hosted invoice page URL
  readonly paidAt: string | null;           // ISO 8601
  readonly createdAt: string;               // ISO 8601
};

/**
 * Paginated invoice list response.
 * Maps to backend InvoiceListResponse in billing/invoice_service.py.
 */
export type InvoiceListResponse = {
  readonly total: number;
  readonly page: number;
  readonly limit: number;
  readonly items: readonly InvoiceSummary[];
};

// -------------------------------------------------------------------------- //
// Billing API request / response types                                          //
// -------------------------------------------------------------------------- //

/**
 * Request payload for upgrading to premium.
 * Maps to backend SubscriptionUpgradeRequest in billing/subscription_service.py.
 */
export type UpgradeRequest = {
  targetTier: "premium";
  paymentMethodId: string;                  // Stripe PaymentMethod ID
};

/**
 * Request to cancel a subscription.
 * Maps to backend SubscriptionCancelRequest in billing/subscription_service.py.
 */
export type CancelSubscriptionRequest = {
  cancelImmediately: boolean;               // false = cancel at period end
};

/**
 * Stripe Checkout Session response.
 * Maps to backend CheckoutSessionResponse in billing/payment_gateway.py.
 */
export type CheckoutSessionResponse = {
  readonly sessionId: string;               // Stripe session ID
  readonly checkoutUrl: string;             // Redirect URL for Stripe Checkout
};

/**
 * Stripe SetupIntent response for saving a payment method.
 * Maps to backend SetupIntentResponse in billing/payment_gateway.py.
 */
export type SetupIntentResponse = {
  readonly clientSecret: string;            // Passed to Stripe.js Elements
  readonly setupIntentId: string;
};

/**
 * Saved payment method summary.
 * Maps to backend PaymentMethodResponse in billing/payment_gateway.py.
 */
export type PaymentMethod = {
  readonly paymentMethodId: string;         // Stripe PM ID
  readonly brand: string;                   // e.g. "visa", "mastercard"
  readonly last4: string;                   // Last 4 digits of card
  readonly expMonth: number;
  readonly expYear: number;
  readonly isDefault: boolean;
};

// -------------------------------------------------------------------------- //
// UI-specific billing types                                                     //
// -------------------------------------------------------------------------- //

/**
 * Plan display configuration for plan selector UI.
 */
export type PlanDisplayConfig = {
  readonly tier: Tier;
  readonly name: string;
  readonly priceUsd: number;
  readonly billingPeriod: "month" | "year";
  readonly features: readonly string[];     // Marketing bullet points
  readonly ctaLabel: string;
  readonly highlighted: boolean;            // Show "popular" badge
};

export const PLAN_DISPLAY_CONFIG: Record<Tier, PlanDisplayConfig> = {
  free: {
    tier: "free",
    name: "Free",
    priceUsd: 0,
    billingPeriod: "month",
    features: [
      "3 videos per month",
      "4 scenes per video",
      "Mathematics, Physics, Chemistry, Biology",
      "General curriculum only",
      "English & Indonesian",
      "Beginner difficulty only",
    ],
    ctaLabel: "Get Started Free",
    highlighted: false,
  },
  premium: {
    tier: "premium",
    name: "Premium",
    priceUsd: 29,
    billingPeriod: "month",
    features: [
      "50 videos per month",
      "Up to 8 scenes per video",
      "All 10 subjects",
      "IB, Cambridge, AP & General",
      "10 languages",
      "All difficulty levels",
      "Priority processing queue",
      "Human expert review",
      "No watermark",
      "Subtitle download (SRT & VTT)",
      "API access",
      "1-year video storage",
    ],
    ctaLabel: "Upgrade to Premium",
    highlighted: true,
  },
};

// -------------------------------------------------------------------------- //
// Type guards and utility functions                                             //
// -------------------------------------------------------------------------- //

/**
 * Type guard: user is on the premium tier with an active subscription.
 */
export function isPremiumActive(subscription: Subscription): boolean {
  return (
    subscription.tier === "premium" &&
    (subscription.status === "active" || subscription.status === "trialing")
  );
}

/**
 * Type guard: subscription is in a trial period.
 */
export function isTrialing(subscription: Subscription): boolean {
  return subscription.status === "trialing" && subscription.trialEnd !== null;
}

/**
 * Type guard: subscription is cancelled but access remains until period end.
 */
export function isCancelledWithAccess(subscription: Subscription): boolean {
  return (
    subscription.cancelAtPeriodEnd &&
    subscription.status === "active" &&
    subscription.currentPeriodEnd !== null
  );
}

/**
 * Get the number of days remaining in the current billing period.
 * Returns null if no period end date is set (free tier).
 */
export function getDaysUntilReset(subscription: Subscription): number | null {
  if (!subscription.currentPeriodEnd) return null;
  const end = new Date(subscription.currentPeriodEnd);
  const now = new Date();
  const diff = end.getTime() - now.getTime();
  return Math.max(0, Math.ceil(diff / (1000 * 60 * 60 * 24)));
}

/**
 * Format USD amount for display (e.g. 29 → "$29.00").
 */
export function formatUsd(amountUsd: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(amountUsd);
  }
