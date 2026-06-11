/**
 * use-subscription-store.ts
 * Subscription tier, quota, and billing UI state.
 * Tier is persisted to localStorage to prevent a flash of "Free" UI
 * on page load for premium users.
 */

import { create } from "zustand";
import { devtools, persist, createJSONStorage } from "zustand/middleware";
import type {
  Subscription,
  QuotaStatus,
  TierFeatures,
  Tier,
} from "@/types";

// -------------------------------------------------------------------------- //
// State + Actions types                                                         //
// -------------------------------------------------------------------------- //

type SubscriptionState = {
  // Server data (refreshed via TanStack Query, mirrored here)
  subscription:   Subscription | null;
  quotaStatus:    QuotaStatus | null;
  tierFeatures:   TierFeatures | null;

  // Derived / cached (persisted to avoid flash)
  tier:           Tier;
  isPremium:      boolean;

  // Loading state
  subscriptionLoading: boolean;
  subscriptionError:   string | null;
  quotaLoading:        boolean;

  // Billing UI
  upgradeModalOpen:   boolean;
  cancelModalOpen:    boolean;
  billingLoadingKey:  string | null;   // which billing action is loading
};

type SubscriptionActions = {
  // Data sync (called by TanStack Query hooks after fetch)
  setSubscription:  (sub: Subscription) => void;
  setQuotaStatus:   (quota: QuotaStatus) => void;
  setTierFeatures:  (features: TierFeatures) => void;

  // Loading
  setSubscriptionLoading: (loading: boolean) => void;
  setSubscriptionError:   (error: string | null) => void;
  setQuotaLoading:        (loading: boolean) => void;

  // Optimistic quota decrement (called immediately on project creation)
  decrementQuota: () => void;
  /** Re-sync quota after a failed creation (undo the optimistic decrement). */
  incrementQuota: () => void;

  // Billing UI
  setUpgradeModalOpen:  (open: boolean) => void;
  setCancelModalOpen:   (open: boolean) => void;
  setBillingLoadingKey: (key: string | null) => void;

  // Feature gate helper
  /** Check if a feature is available on the current tier. */
  canUseFeature: (featureKey: keyof TierFeatures) => boolean;
  /** Check if a specific subject is allowed on current tier. */
  canUseSubject: (subject: string) => boolean;
  /** Check if a specific curriculum is allowed on current tier. */
  canUseCurriculum: (curriculum: string) => boolean;

  // Reset
  reset: () => void;
};

// -------------------------------------------------------------------------- //
// Initial state                                                                 //
// -------------------------------------------------------------------------- //

const INITIAL_STATE: SubscriptionState = {
  subscription:        null,
  quotaStatus:         null,
  tierFeatures:        null,
  tier:                "free",
  isPremium:           false,
  subscriptionLoading: false,
  subscriptionError:   null,
  quotaLoading:        false,
  upgradeModalOpen:    false,
  cancelModalOpen:     false,
  billingLoadingKey:   null,
};

// -------------------------------------------------------------------------- //
// Store                                                                         //
// -------------------------------------------------------------------------- //

export const useSubscriptionStore = create<
  SubscriptionState & SubscriptionActions
>()(
  devtools(
    persist(
      (set, get) => ({
        ...INITIAL_STATE,

        // ----------------------------------------------------------------- //
        // Data sync                                                           //
        // ----------------------------------------------------------------- //

        setSubscription: (sub) =>
          set(
            {
              subscription:        sub,
              tier:                sub.tier,
              isPremium:           sub.tier === "premium" &&
                                   (sub.status === "active" || sub.status === "trialing"),
              subscriptionError:   null,
              subscriptionLoading: false,
            },
            false,
            "setSubscription"
          ),

        setQuotaStatus: (quota) =>
          set({ quotaStatus: quota, quotaLoading: false }, false, "setQuotaStatus"),

        setTierFeatures: (features) =>
          set({ tierFeatures: features }, false, "setTierFeatures"),

        // ----------------------------------------------------------------- //
        // Loading                                                              //
        // ----------------------------------------------------------------- //

        setSubscriptionLoading: (loading) =>
          set({ subscriptionLoading: loading }, false, "setSubscriptionLoading"),

        setSubscriptionError: (error) =>
          set(
            { subscriptionError: error, subscriptionLoading: false },
            false,
            "setSubscriptionError"
          ),

        setQuotaLoading: (loading) =>
          set({ quotaLoading: loading }, false, "setQuotaLoading"),

        // ----------------------------------------------------------------- //
        // Optimistic quota management                                          //
        // ----------------------------------------------------------------- //

        decrementQuota: () =>
          set(
            (s) => {
              if (!s.quotaStatus) return {};
              const newUsed     = s.quotaStatus.videosUsed + 1;
              const newRemaining = Math.max(0, s.quotaStatus.videosRemaining - 1);
              return {
                quotaStatus: {
                  ...s.quotaStatus,
                  videosUsed:       newUsed,
                  videosRemaining:  newRemaining,
                  percentageUsed:   s.quotaStatus.videosLimit > 0
                    ? Math.min(100, Math.round((newUsed / s.quotaStatus.videosLimit) * 100))
                    : 100,
                  isExceeded: newRemaining === 0,
                },
              };
            },
            false,
            "decrementQuota"
          ),

        incrementQuota: () =>
          set(
            (s) => {
              if (!s.quotaStatus) return {};
              const newUsed     = Math.max(0, s.quotaStatus.videosUsed - 1);
              const newRemaining = s.quotaStatus.videosLimit - newUsed;
              return {
                quotaStatus: {
                  ...s.quotaStatus,
                  videosUsed:      newUsed,
                  videosRemaining: Math.max(0, newRemaining),
                  percentageUsed:  s.quotaStatus.videosLimit > 0
                    ? Math.min(100, Math.round((newUsed / s.quotaStatus.videosLimit) * 100))
                    : 0,
                  isExceeded: false,
                },
              };
            },
            false,
            "incrementQuota"
          ),

        // ----------------------------------------------------------------- //
        // Billing UI                                                           //
        // ----------------------------------------------------------------- //

        setUpgradeModalOpen: (open) =>
          set({ upgradeModalOpen: open }, false, "setUpgradeModalOpen"),

        setCancelModalOpen: (open) =>
          set({ cancelModalOpen: open }, false, "setCancelModalOpen"),

        setBillingLoadingKey: (key) =>
          set({ billingLoadingKey: key }, false, "setBillingLoadingKey"),

        // ----------------------------------------------------------------- //
        // Feature gate helpers                                                 //
        // ----------------------------------------------------------------- //

        canUseFeature: (featureKey) => {
          const { tierFeatures } = get();
          if (!tierFeatures) return false;
          const val = tierFeatures[featureKey];
          if (typeof val === "boolean") return val;
          if (Array.isArray(val)) return val.length > 0;
          if (typeof val === "number") return val > 0;
          return Boolean(val);
        },

        canUseSubject: (subject) => {
          const { tierFeatures } = get();
          if (!tierFeatures) return false;
          return tierFeatures.allowedSubjects.includes(subject);
        },

        canUseCurriculum: (curriculum) => {
          const { tierFeatures } = get();
          if (!tierFeatures) return false;
          return tierFeatures.allowedCurricula.includes(curriculum);
        },

        // ----------------------------------------------------------------- //
        // Reset                                                                //
        // ----------------------------------------------------------------- //

        reset: () => set(INITIAL_STATE, false, "reset"),
      }),
      {
        name:    "eduvideo-subscription",
        storage: createJSONStorage(() => localStorage),
        // Only persist tier + isPremium to avoid stale subscription object
        partialize: (s) => ({
          tier:      s.tier,
          isPremium: s.isPremium,
        }),
      }
    ),
    { name: "EduVideo:Subscription" }
  )
);

// -------------------------------------------------------------------------- //
// Selectors                                                                     //
// -------------------------------------------------------------------------- //

type S = SubscriptionState & SubscriptionActions;

/** Current tier and premium status — persisted, safe to read on first render. */
export const selectTier = (s: S) => ({
  tier:      s.tier,
  isPremium: s.isPremium,
});

/** Quota meter data for the usage bar. */
export const selectQuotaMeter = (s: S) => ({
  used:          s.quotaStatus?.videosUsed    ?? 0,
  limit:         s.quotaStatus?.videosLimit   ?? 3,
  remaining:     s.quotaStatus?.videosRemaining ?? 3,
  percent:       s.quotaStatus?.percentageUsed  ?? 0,
  isExceeded:    s.quotaStatus?.isExceeded       ?? false,
  resetsAt:      s.quotaStatus?.resetsAt         ?? null,
  loading:       s.quotaLoading,
});

/** Subscription record and loading state. */
export const selectSubscription = (s: S) => ({
  subscription: s.subscription,
  loading:      s.subscriptionLoading,
  error:        s.subscriptionError,
});

/** Billing modal open/close state. */
export const selectBillingModals = (s: S) => ({
  upgradeOpen:      s.upgradeModalOpen,
  cancelOpen:       s.cancelModalOpen,
  loadingKey:       s.billingLoadingKey,
});

/** True if the user has exhausted their monthly quota. */
export const selectIsQuotaExceeded = (s: S): boolean =>
  s.quotaStatus?.isExceeded ?? false;

/** True if subscription is in trial period. */
export const selectIsTrialing = (s: S): boolean =>
  s.subscription?.status === "trialing";
