"use client";

/**
 * use-billing.ts
 * Hooks for Stripe upgrade/cancel flows, payment methods, and invoices.
 */

import { useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  initiateCheckout,
  upgradeToPremium,
  cancelCurrentSubscription,
  loadPaymentMethods,
  loadInvoices,
  resendInvoiceEmail,
  deletePaymentMethod,
} from "@/services/billing-service";
import {
  useSubscriptionStore,
  selectBillingModals,
  selectTier,
} from "@/store";
import { QUERY_KEYS, ROUTES } from "@/lib/constants";
import { toast } from "@/providers";

// -------------------------------------------------------------------------- //
// useBillingUpgrade                                                           //
// -------------------------------------------------------------------------- //

/**
 * Manage the upgrade to Premium flow.
 * Supports both Stripe Checkout redirect and in-app upgrade with saved card.
 *
 * @returns upgrade actions, modal state, loading key
 *
 * @example
 *   const { openUpgradeModal, upgradeWithCheckout, upgradeWithSavedCard } =
 *     useBillingUpgrade();
 */
export function useBillingUpgrade() {
  const queryClient  = useQueryClient();
  const store        = useSubscriptionStore();
  const { upgradeOpen, loadingKey } = useSubscriptionStore(selectBillingModals);
  const { isPremium }               = useSubscriptionStore(selectTier);

  const checkoutMutation = useMutation({
    mutationFn: () =>
      initiateCheckout(
        `${window.location.origin}${ROUTES.billing}?upgraded=true`,
        `${window.location.origin}${ROUTES.billing}`
      ),
    onSuccess: (result) => {
      if (result.success) {
        window.location.href = result.data.checkoutUrl;
      } else {
        toast.error(result.error);
      }
    },
    onError: () => toast.error("Failed to start checkout. Please try again."),
  });

  const savedCardMutation = useMutation({
    mutationFn: (paymentMethodId: string) => upgradeToPremium(paymentMethodId),
    onSuccess: (result) => {
      if (result.success) {
        toast.success("Welcome to Premium!", {
          description: "All subjects and curricula are now unlocked.",
        });
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.billing.all() });
        store.setUpgradeModalOpen(false);
      } else {
        toast.error(result.error);
      }
    },
    onError: () => toast.error("Upgrade failed. Please try again."),
  });

  return {
    isPremium,
    upgradeOpen,
    loadingKey,
    openUpgradeModal:    () => store.setUpgradeModalOpen(true),
    closeUpgradeModal:   () => store.setUpgradeModalOpen(false),
    upgradeWithCheckout: checkoutMutation.mutate,
    upgradeWithSavedCard: (pmId: string) => savedCardMutation.mutate(pmId),
    isCheckoutLoading:   checkoutMutation.isPending,
    isSavedCardLoading:  savedCardMutation.isPending,
  };
}

// -------------------------------------------------------------------------- //
// useBillingCancel                                                            //
// -------------------------------------------------------------------------- //

/**
 * Manage the subscription cancellation flow.
 *
 * @returns cancel action, modal state
 */
export function useBillingCancel() {
  const queryClient = useQueryClient();
  const store       = useSubscriptionStore();
  const { cancelOpen } = useSubscriptionStore(selectBillingModals);

  const mutation = useMutation({
    mutationFn: (immediately: boolean) => cancelCurrentSubscription(immediately),
    onSuccess: (result) => {
      if (result.success) {
        const msg = result.data.cancelAtPeriodEnd
          ? "Subscription cancelled — you retain access until your billing period ends."
          : "Subscription cancelled immediately.";
        toast.info(msg);
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.billing.all() });
        store.setCancelModalOpen(false);
      } else {
        toast.error(result.error);
      }
    },
    onError: () => toast.error("Cancellation failed. Please contact support."),
  });

  return {
    cancelOpen,
    openCancelModal:  () => store.setCancelModalOpen(true),
    closeCancelModal: () => store.setCancelModalOpen(false),
    cancel:           (immediately = false) => mutation.mutate(immediately),
    isCancelling:     mutation.isPending,
  };
}

// -------------------------------------------------------------------------- //
// usePaymentMethods                                                           //
// -------------------------------------------------------------------------- //

/**
 * Load and manage saved payment methods.
 *
 * @returns Payment methods list + remove action
 */
export function usePaymentMethods() {
  const queryClient = useQueryClient();

  const { data: result, isLoading } = useQuery({
    queryKey: QUERY_KEYS.billing.paymentMethods(),
    queryFn:  loadPaymentMethods,
    staleTime: 5 * 60 * 1_000,
  });

  const removeMutation = useMutation({
    mutationFn: (pmId: string) => deletePaymentMethod(pmId),
    onSuccess: (result, pmId) => {
      if (result.success) {
        toast.success("Payment method removed");
        queryClient.invalidateQueries({
          queryKey: QUERY_KEYS.billing.paymentMethods(),
        });
      } else {
        toast.error(result.error);
      }
    },
    onError: () => toast.error("Failed to remove payment method."),
  });

  const methods = result?.success ? result.data : [];

  return {
    paymentMethods: methods,
    isLoading,
    remove:          (pmId: string) => removeMutation.mutate(pmId),
    isRemoving:      removeMutation.isPending,
    removingId:      removeMutation.variables ?? null,
  };
}

// -------------------------------------------------------------------------- //
// useInvoices                                                                 //
// -------------------------------------------------------------------------- //

/**
 * Load paginated invoice history.
 *
 * @param page - Current page number (default 1)
 * @returns Invoices list, pagination state, resend action
 */
export function useInvoices(page = 1) {
  const { data: result, isLoading } = useQuery({
    queryKey: QUERY_KEYS.billing.invoices(page),
    queryFn:  () => loadInvoices(page, 10),
    staleTime: 15 * 60 * 1_000,
  });

  const resendMutation = useMutation({
    mutationFn: (invoiceId: string) => resendInvoiceEmail(invoiceId),
    onSuccess: (result) => {
      if (result.success) {
        toast.success("Invoice email sent");
      } else {
        toast.error(result.error);
      }
    },
  });

  const response = result?.success ? result.data : null;

  return {
    invoices:    response?.items  ?? [],
    total:       response?.total  ?? 0,
    isLoading,
    resend:      (id: string) => resendMutation.mutate(id),
    isResending: resendMutation.isPending,
    resendingId: resendMutation.variables ?? null,
  };
                                                                     }
