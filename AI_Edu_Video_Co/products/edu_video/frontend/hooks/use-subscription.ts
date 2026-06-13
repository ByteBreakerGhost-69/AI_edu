"use client";

/**
 * use-subscription.ts
 * Hooks for subscription tier, quota display, and feature gating.
 */

import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { loadSubscriptionData, refreshQuota } from "@/services/billing-service";
import {
  useSubscriptionStore,
  selectTier,
  selectQuotaMeter,
  selectSubscription,
  selectIsQuotaExceeded,
} from "@/store";
import { QUERY_KEYS } from "@/lib/constants";
import type { TierFeatures } from "@/types";

// -------------------------------------------------------------------------- //
// useSubscription                                                             //
// -------------------------------------------------------------------------- //

/**
 * Load and expose the user's subscription data.
 * Syncs server state into the subscription store on first load.
 *
 * @returns Subscription record, tier, and loading state
 *
 * @example
 *   const { subscription, tier, isPremium, isLoading } = useSubscription();
 */
export function useSubscription() {
  const { subscription, loading, error } = useSubscriptionStore(selectSubscription);
  const { tier, isPremium }              = useSubscriptionStore(selectTier);

  useQuery({
    queryKey: QUERY_KEYS.billing.subscription(),
    queryFn:  loadSubscriptionData,
    staleTime: 5 * 60 * 1_000,
    enabled:  !subscription, // Skip if already loaded
  });

  return {
    subscription,
    tier,
    isPremium,
    isLoading: loading,
    error,
  };
}

// -------------------------------------------------------------------------- //
// useQuota                                                                    //
// -------------------------------------------------------------------------- //

/**
 * Track monthly video quota usage with live refresh.
 *
 * @returns Quota counts, percentage, reset date, and refresh action
 *
 * @example
 *   const { used, limit, remaining, percent, isExceeded } = useQuota();
 */
export function useQuota() {
  const meter      = useSubscriptionStore(selectQuotaMeter);
  const isExceeded = useSubscriptionStore(selectIsQuotaExceeded);

  const { refetch } = useQuery({
    queryKey:  QUERY_KEYS.billing.quota(),
    queryFn:   refreshQuota,
    staleTime: 30_000,
    refetchInterval: isExceeded ? 10_000 : false, // Poll faster when at limit
  });

  return {
    used:       meter.used,
    limit:      meter.limit,
    remaining:  meter.remaining,
    percent:    meter.percent,
    isExceeded,
    resetsAt:   meter.resetsAt,
    isLoading:  meter.loading,
    refresh:    refetch,
  };
}

// -------------------------------------------------------------------------- //
// useFeatureGate                                                              //
// -------------------------------------------------------------------------- //

/**
 * Check whether a TierFeatures key is available on the current tier.
 *
 * @param featureKey - Key from TierFeatures interface
 * @returns { allowed, reason } — use to conditionally render premium gates
 *
 * @example
 *   const { allowed } = useFeatureGate("subtitleDownload");
 *   if (!allowed) return <PremiumGate />;
 */
export function useFeatureGate(featureKey: keyof TierFeatures) {
  const store = useSubscriptionStore();

  const allowed = useCallback(
    () => store.canUseFeature(featureKey),
    [store, featureKey]
  );

  const { tier, isPremium } = useSubscriptionStore(selectTier);

  return {
    allowed:         allowed(),
    upgradeRequired: !isPremium,
    currentTier:     tier,
  };
}

// -------------------------------------------------------------------------- //
// useSubjectGate / useCurriculumGate                                          //
// -------------------------------------------------------------------------- //

/**
 * Check whether a specific subject is available on the current tier.
 *
 * @param subject - Subject string e.g. "history"
 * @returns allowed boolean and upgradeRequired flag
 */
export function useSubjectGate(subject: string) {
  const store      = useSubscriptionStore();
  const { isPremium } = useSubscriptionStore(selectTier);

  return {
    allowed:         store.canUseSubject(subject),
    upgradeRequired: !store.canUseSubject(subject) && !isPremium,
  };
}

/**
 * Check whether a specific curriculum is available on the current tier.
 *
 * @param curriculum - Curriculum string e.g. "IB"
 */
export function useCurriculumGate(curriculum: string) {
  const store      = useSubscriptionStore();
  const { isPremium } = useSubscriptionStore(selectTier);

  return {
    allowed:         store.canUseCurriculum(curriculum),
    upgradeRequired: !store.canUseCurriculum(curriculum) && !isPremium,
  };
    }
