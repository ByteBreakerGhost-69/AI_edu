/**
 * billing-api.ts
 * Endpoints for subscription management, payment methods, invoices, and quota.
 */

import { apiGet, apiPost, apiDelete, withRetry } from "./client";
import type {
  Subscription,
  QuotaStatus,
  InvoiceListResponse,
  InvoiceSummary,
  UpgradeRequest,
  CancelSubscriptionRequest,
  CheckoutSessionResponse,
  SetupIntentResponse,
  PaymentMethod,
} from "@/types";

const BILLING_BASE = "/api/v1/billing";

// -------------------------------------------------------------------------- //
// Subscription                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Fetch the authenticated user's current subscription.
 *
 * Endpoint: GET /api/v1/billing/subscription
 *
 * Creates a free-tier subscription record automatically if none exists
 * (new users get free tier on first access).
 *
 * @returns Current subscription with tier, status, and TierFeatures
 */
export async function getSubscription(): Promise<Subscription> {
  return withRetry(() =>
    apiGet<Subscription>(`${BILLING_BASE}/subscription`)
  );
}

/**
 * Upgrade from free to premium via a saved Stripe PaymentMethod.
 *
 * Endpoint: POST /api/v1/billing/subscription/upgrade
 *
 * Requires a PaymentMethod ID from Stripe Elements (use createSetupIntent
 * to collect and save the card before calling this).
 *
 * @param payload - Target tier ("premium") + Stripe PaymentMethod ID
 * @returns Updated subscription with new tier and period dates
 *
 * @throws ApiError(402) Stripe payment declined
 * @throws ApiError(409) already on premium tier
 * @throws ApiError(422) invalid payment method ID
 */
export async function upgradeSubscription(
  payload: UpgradeRequest
): Promise<Subscription> {
  return apiPost<Subscription>(
    `${BILLING_BASE}/subscription/upgrade`,
    payload
  );
}

/**
 * Cancel the current premium subscription.
 *
 * Endpoint: POST /api/v1/billing/subscription/cancel
 *
 * cancelImmediately=false (default): subscription remains active until
 * the end of the current billing period, then downgrades to free.
 *
 * cancelImmediately=true: subscription cancelled now, access revoked
 * immediately, prorated refund may be issued via Stripe.
 *
 * @param payload - Whether to cancel immediately or at period end
 * @returns Updated subscription showing cancelAtPeriodEnd=true or status="cancelled"
 *
 * @throws ApiError(404) no active premium subscription found
 */
export async function cancelSubscription(
  payload: CancelSubscriptionRequest
): Promise<Subscription> {
  return apiPost<Subscription>(
    `${BILLING_BASE}/subscription/cancel`,
    payload
  );
}

// -------------------------------------------------------------------------- //
// Stripe Checkout                                                               //
// -------------------------------------------------------------------------- //

/**
 * Parameters for creating a Stripe Checkout session.
 */
export type CreateCheckoutParams = {
  successUrl: string;    // Redirect URL after successful payment
  cancelUrl: string;     // Redirect URL if user cancels Checkout
  trial?: boolean;       // Whether to include trial period (default: true)
};

/**
 * Create a Stripe Checkout Session for upgrading to premium.
 *
 * Endpoint: POST /api/v1/billing/checkout
 *
 * Redirect the user to checkoutUrl to complete payment.
 * After successful payment, Stripe sends a webhook which updates the
 * subscription in the backend database automatically.
 *
 * @param params - Success URL, cancel URL, and optional trial flag
 * @returns Checkout session ID and redirect URL
 *
 * @throws ApiError(409) already on premium tier
 */
export async function createCheckoutSession(
  params: CreateCheckoutParams
): Promise<CheckoutSessionResponse> {
  return apiPost<CheckoutSessionResponse>(`${BILLING_BASE}/checkout`, params);
}

// -------------------------------------------------------------------------- //
// Payment methods                                                               //
// -------------------------------------------------------------------------- //

/**
 * Create a Stripe SetupIntent for saving a payment method without charging.
 *
 * Endpoint: POST /api/v1/billing/setup-intent
 *
 * Pass the returned clientSecret to Stripe.js Elements to collect card details.
 * After the SetupIntent confirms, pass the resulting PaymentMethod ID to
 * upgradeSubscription().
 *
 * @returns SetupIntent client_secret for Stripe.js + setupIntentId
 */
export async function createSetupIntent(): Promise<SetupIntentResponse> {
  return apiPost<SetupIntentResponse>(`${BILLING_BASE}/setup-intent`);
}

/**
 * Fetch all saved payment methods for the authenticated user.
 *
 * Endpoint: GET /api/v1/billing/payment-methods
 *
 * @returns Array of saved cards (brand, last4, expiry, isDefault)
 */
export async function listPaymentMethods(): Promise<PaymentMethod[]> {
  return withRetry(() =>
    apiGet<PaymentMethod[]>(`${BILLING_BASE}/payment-methods`)
  );
}

/**
 * Remove a saved payment method.
 *
 * Endpoint: DELETE /api/v1/billing/payment-methods/{payment_method_id}
 *
 * @param paymentMethodId - Stripe PaymentMethod ID (pm_xxx)
 *
 * @throws ApiError(404) payment method not found
 * @throws ApiError(409) cannot remove default method while subscription is active
 */
export async function removePaymentMethod(
  paymentMethodId: string
): Promise<void> {
  return apiDelete<void>(
    `${BILLING_BASE}/payment-methods/${paymentMethodId}`
  );
}

// -------------------------------------------------------------------------- //
// Quota                                                                         //
// -------------------------------------------------------------------------- //

/**
 * Fetch the current monthly video quota status.
 *
 * Endpoint: GET /api/v1/billing/quota
 *
 * Returns real-time quota: used, limit, remaining, and reset date.
 * Use this to drive the UsageMeter component and enforce gates in the UI
 * before the user reaches the backend 402 error.
 *
 * @returns Quota status with used/remaining counts and period reset date
 */
export async function getQuotaStatus(): Promise<QuotaStatus> {
  return withRetry(() => apiGet<QuotaStatus>(`${BILLING_BASE}/quota`));
}

// -------------------------------------------------------------------------- //
// Invoices                                                                      //
// -------------------------------------------------------------------------- //

/**
 * Query params for invoice list.
 */
export type InvoiceListParams = {
  page?: number;
  limit?: number;
};

/**
 * Fetch paginated invoice history for the authenticated user.
 *
 * Endpoint: GET /api/v1/billing/invoices
 *
 * Returns invoices sorted newest-first.
 * Each invoice includes the PDF URL and hosted Stripe invoice page URL.
 *
 * @param params - Optional pagination (page, limit)
 * @returns Paginated invoice list with total count
 */
export async function listInvoices(
  params?: InvoiceListParams
): Promise<InvoiceListResponse> {
  return withRetry(() =>
    apiGet<InvoiceListResponse>(
      `${BILLING_BASE}/invoices`,
      params as Record<string, unknown>
    )
  );
}

/**
 * Fetch a single invoice by its UUID.
 *
 * Endpoint: GET /api/v1/billing/invoices/{invoice_id}
 *
 * @param invoiceId - UUID of the invoice
 * @returns Full invoice details
 *
 * @throws ApiError(404) invoice not found or belongs to another user
 */
export async function getInvoice(invoiceId: string): Promise<InvoiceSummary> {
  return withRetry(() =>
    apiGet<InvoiceSummary>(`${BILLING_BASE}/invoices/${invoiceId}`)
  );
}

/**
 * Request re-sending of an invoice to the user's email.
 *
 * Endpoint: POST /api/v1/billing/invoices/{invoice_id}/send
 *
 * Triggers Stripe to re-send the invoice email.
 *
 * @param invoiceId - UUID of the invoice to resend
 *
 * @throws ApiError(404) invoice not found
 * @throws ApiError(422) invoice not linked to a Stripe invoice
 * @throws ApiError(502) Stripe API error
 */
export async function sendInvoiceEmail(invoiceId: string): Promise<void> {
  return apiPost<void>(`${BILLING_BASE}/invoices/${invoiceId}/send`);
}
