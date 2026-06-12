/**
 * billing-service.ts
 * Subscription management, Stripe flows, invoice retrieval, and quota sync.
 */

import {
  getSubscription,
  getQuotaStatus,
  createCheckoutSession,
  createSetupIntent,
  upgradeSubscription,
  cancelSubscription,
  listPaymentMethods,
  removePaymentMethod,
  listInvoices,
  getInvoice,
  sendInvoiceEmail,
} from "@/lib/api/billing-api";
import type {
  Subscription,
  QuotaStatus,
  PaymentMethod,
  InvoiceSummary,
  InvoiceListResponse,
  CheckoutSessionResponse,
  SetupIntentResponse,
} from "@/types";
import type { ApiError } from "@/lib/api/client";
import type { ServiceResult } from "./project-service";

export type { ServiceResult };

// -------------------------------------------------------------------------- //
// loadSubscriptionData                                                          //
// -------------------------------------------------------------------------- //

/**
 * Load and sync subscription + quota status into the subscription store.
 * Call on initial app load and after any billing action.
 *
 * @returns ServiceResult with subscription and quota
 */
export async function loadSubscriptionData(): Promise<
  ServiceResult<{ subscription: Subscription; quota: QuotaStatus }>
> {
  const { useSubscriptionStore } = await import("@/store");

  useSubscriptionStore.getState().setSubscriptionLoading(true);
  useSubscriptionStore.getState().setQuotaLoading(true);

  try {
    const [subResult, quotaResult] = await Promise.allSettled([
      getSubscription(),
      getQuotaStatus(),
    ]);

    if (subResult.status === "rejected") {
      const err = subResult.reason as ApiError;
      useSubscriptionStore.getState().setSubscriptionError(
        err.detail ?? "Failed to load subscription."
      );
      return { success: false, error: err.detail ?? "Failed to load subscription." };
    }

    const sub   = (subResult   as PromiseFulfilledResult<Subscription>).value;
    const quota = quotaResult.status === "fulfilled"
      ? (quotaResult as PromiseFulfilledResult<QuotaStatus>).value
      : null;

    useSubscriptionStore.getState().setSubscription(sub);
    if (quota) useSubscriptionStore.getState().setQuotaStatus(quota);

    useSubscriptionStore.getState().setSubscriptionLoading(false);
    useSubscriptionStore.getState().setQuotaLoading(false);

    return {
      success: true,
      data:    {
        subscription: sub,
        quota:        quota ?? ({
          userId:          "",
          tier:            sub.tier,
          videosUsed:      sub.videosUsed,
          videosLimit:     sub.videosLimit,
          videosRemaining: Math.max(0, sub.videosLimit - sub.videosUsed),
          resetsAt:        sub.currentPeriodEnd ?? new Date().toISOString(),
          isExceeded:      sub.videosUsed >= sub.videosLimit,
          percentageUsed:  sub.videosLimit > 0
            ? Math.min(100, Math.round((sub.videosUsed / sub.videosLimit) * 100))
            : 100,
        } as QuotaStatus),
      },
    };
  } catch (error) {
    const err = error as ApiError;
    useSubscriptionStore.getState().setSubscriptionError(
      err.detail ?? "Failed to load subscription data."
    );
    return { success: false, error: err.detail ?? "Failed to load subscription data." };
  }
}

// -------------------------------------------------------------------------- //
// initiateCheckout                                                              //
// -------------------------------------------------------------------------- //

/**
 * Create a Stripe Checkout session for upgrading to premium.
 * Redirects to Stripe-hosted checkout page.
 *
 * @param successUrl - URL to redirect after successful payment
 * @param cancelUrl  - URL to redirect if user cancels Checkout
 * @returns ServiceResult with checkoutUrl to redirect the user to
 */
export async function initiateCheckout(
  successUrl: string,
  cancelUrl: string
): Promise<ServiceResult<{ checkoutUrl: string }>> {
  const { useSubscriptionStore } = await import("@/store");

  useSubscriptionStore.getState().setBillingLoadingKey("checkout");

  try {
    const session = await createCheckoutSession({ successUrl, cancelUrl });
    useSubscriptionStore.getState().setBillingLoadingKey(null);
    return { success: true, data: { checkoutUrl: session.checkoutUrl } };
  } catch (error) {
    const err = error as ApiError;
    useSubscriptionStore.getState().setBillingLoadingKey(null);

    if (err.statusCode === 409) {
      return { success: false, error: "You are already on the Premium plan." };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to start checkout. Please try again.",
    };
  }
}

// -------------------------------------------------------------------------- //
// getSetupIntentForPaymentMethod                                                //
// -------------------------------------------------------------------------- //

/**
 * Create a Stripe SetupIntent to collect a new payment method without charging.
 * The returned clientSecret is passed to Stripe.js Elements.
 *
 * @returns ServiceResult with clientSecret for Stripe Elements
 */
export async function getSetupIntentForPaymentMethod(): Promise<
  ServiceResult<SetupIntentResponse>
> {
  const { useSubscriptionStore } = await import("@/store");

  useSubscriptionStore.getState().setBillingLoadingKey("setup_intent");

  try {
    const intent = await createSetupIntent();
    useSubscriptionStore.getState().setBillingLoadingKey(null);
    return { success: true, data: intent };
  } catch (error) {
    const err = error as ApiError;
    useSubscriptionStore.getState().setBillingLoadingKey(null);
    return {
      success: false,
      error: err.detail ?? "Failed to set up payment method. Please try again.",
    };
  }
}

// -------------------------------------------------------------------------- //
// upgradeToPremiun                                                              //
// -------------------------------------------------------------------------- //

/**
 * Upgrade the user to Premium using a saved Stripe PaymentMethod.
 * Updates subscription store on success.
 *
 * @param paymentMethodId - Stripe PaymentMethod ID from SetupIntent
 * @returns ServiceResult with updated Subscription
 */
export async function upgradeToPremium(
  paymentMethodId: string
): Promise<ServiceResult<Subscription>> {
  const { useSubscriptionStore } = await import("@/store");

  useSubscriptionStore.getState().setBillingLoadingKey("upgrade");

  try {
    const updated = await upgradeSubscription({
      targetTier:      "premium",
      paymentMethodId,
    });

    useSubscriptionStore.getState().setSubscription(updated);
    useSubscriptionStore.getState().setUpgradeModalOpen(false);
    useSubscriptionStore.getState().setBillingLoadingKey(null);

    return { success: true, data: updated };
  } catch (error) {
    const err = error as ApiError;
    useSubscriptionStore.getState().setBillingLoadingKey(null);

    if (err.statusCode === 402) {
      return {
        success: false,
        error:   "Payment declined. Please check your card details and try again.",
      };
    }

    if (err.statusCode === 409) {
      return { success: false, error: "You are already on the Premium plan." };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to upgrade subscription. Please try again.",
    };
  }
}

// -------------------------------------------------------------------------- //
// cancelCurrentSubscription                                                     //
// -------------------------------------------------------------------------- //

/**
 * Cancel the user's premium subscription.
 * Updates subscription store on success.
 * cancelImmediately=false is the default (access until period end).
 *
 * @param cancelImmediately - Whether to revoke access immediately
 * @returns ServiceResult with updated Subscription
 */
export async function cancelCurrentSubscription(
  cancelImmediately = false
): Promise<ServiceResult<Subscription>> {
  const { useSubscriptionStore } = await import("@/store");

  useSubscriptionStore.getState().setBillingLoadingKey("cancel");

  try {
    const updated = await cancelSubscription({ cancelImmediately });

    useSubscriptionStore.getState().setSubscription(updated);
    useSubscriptionStore.getState().setCancelModalOpen(false);
    useSubscriptionStore.getState().setBillingLoadingKey(null);

    return { success: true, data: updated };
  } catch (error) {
    const err = error as ApiError;
    useSubscriptionStore.getState().setBillingLoadingKey(null);

    if (err.isNotFound) {
      return {
        success: false,
        error:   "No active Premium subscription found.",
      };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to cancel subscription. Please try again.",
    };
  }
}

// -------------------------------------------------------------------------- //
// loadPaymentMethods                                                            //
// -------------------------------------------------------------------------- //

/**
 * Fetch saved payment methods for the billing settings page.
 *
 * @returns ServiceResult with array of PaymentMethod
 */
export async function loadPaymentMethods(): Promise<ServiceResult<PaymentMethod[]>> {
  try {
    const methods = await listPaymentMethods();
    return { success: true, data: methods };
  } catch (error) {
    const err = error as ApiError;
    return {
      success: false,
      error: err.detail ?? "Failed to load payment methods.",
    };
  }
}

// -------------------------------------------------------------------------- //
// deletePaymentMethod                                                           //
// -------------------------------------------------------------------------- //

/**
 * Remove a saved payment method.
 *
 * @param paymentMethodId - Stripe PaymentMethod ID to remove
 * @returns ServiceResult<void>
 */
export async function deletePaymentMethod(
  paymentMethodId: string
): Promise<ServiceResult> {
  const { useSubscriptionStore } = await import("@/store");

  useSubscriptionStore.getState().setBillingLoadingKey(`remove_pm_${paymentMethodId}`);

  try {
    await removePaymentMethod(paymentMethodId);
    useSubscriptionStore.getState().setBillingLoadingKey(null);
    return { success: true, data: undefined };
  } catch (error) {
    const err = error as ApiError;
    useSubscriptionStore.getState().setBillingLoadingKey(null);

    if (err.statusCode === 409) {
      return {
        success: false,
        error:   "Cannot remove your default payment method while you have an active subscription.",
      };
    }

    return {
      success: false,
      error: err.detail ?? "Failed to remove payment method.",
    };
  }
}

// -------------------------------------------------------------------------- //
// loadInvoices                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Load paginated invoice history for the billing invoices page.
 *
 * @param page - Page number (default 1)
 * @param limit - Items per page (default 10)
 * @returns ServiceResult with InvoiceListResponse
 */
export async function loadInvoices(
  page = 1,
  limit = 10
): Promise<ServiceResult<InvoiceListResponse>> {
  try {
    const response = await listInvoices({ page, limit });
    return { success: true, data: response };
  } catch (error) {
    const err = error as ApiError;
    return { success: false, error: err.detail ?? "Failed to load invoices." };
  }
}

// -------------------------------------------------------------------------- //
// loadInvoiceDetail                                                             //
// -------------------------------------------------------------------------- //

/**
 * Load a single invoice for the invoice detail modal.
 *
 * @param invoiceId - UUID of the invoice
 * @returns ServiceResult with InvoiceSummary
 */
export async function loadInvoiceDetail(
  invoiceId: string
): Promise<ServiceResult<InvoiceSummary>> {
  try {
    const invoice = await getInvoice(invoiceId);
    return { success: true, data: invoice };
  } catch (error) {
    const err = error as ApiError;
    if (err.isNotFound) {
      return { success: false, error: "Invoice not found." };
    }
    return { success: false, error: err.detail ?? "Failed to load invoice." };
  }
}

// -------------------------------------------------------------------------- //
// resendInvoiceEmail                                                            //
// -------------------------------------------------------------------------- //

/**
 * Re-send an invoice email to the user's registered email address.
 *
 * @param invoiceId - UUID of the invoice to resend
 * @returns ServiceResult<void>
 */
export async function resendInvoiceEmail(
  invoiceId: string
): Promise<ServiceResult> {
  try {
    await sendInvoiceEmail(invoiceId);
    return { success: true, data: undefined };
  } catch (error) {
    const err = error as ApiError;
    if (err.isNotFound) {
      return { success: false, error: "Invoice not found." };
    }
    if (err.statusCode === 502) {
      return {
        success: false,
        error:   "Email delivery failed. Please try again in a few minutes.",
      };
    }
    return { success: false, error: err.detail ?? "Failed to send invoice email." };
  }
}

// -------------------------------------------------------------------------- //
// refreshQuota                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Re-fetch and sync quota status from the server.
 * Call after project creation or when the usage meter needs to be accurate.
 *
 * @returns ServiceResult with fresh QuotaStatus
 */
export async function refreshQuota(): Promise<ServiceResult<QuotaStatus>> {
  const { useSubscriptionStore } = await import("@/store");

  useSubscriptionStore.getState().setQuotaLoading(true);

  try {
    const quota = await getQuotaStatus();
    useSubscriptionStore.getState().setQuotaStatus(quota);
    return { success: true, data: quota };
  } catch (error) {
    const err = error as ApiError;
    useSubscriptionStore.getState().setQuotaLoading(false);
    return { success: false, error: err.detail ?? "Failed to refresh quota." };
  }
    }
