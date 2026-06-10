/**
 * lib/validators/index.ts
 * All Zod validation schemas for the EduVideo platform.
 * Every schema produces an inferred TypeScript type.
 * These are consumed by React Hook Form via zodResolver.
 */

import { z } from "zod";
import {
  SUBJECTS,
  CURRICULA,
  DIFFICULTY_LEVELS,
  LANGUAGES,
  FEEDBACK_TYPES,
} from "@/types";

// -------------------------------------------------------------------------- //
// Reusable primitives                                                           //
// -------------------------------------------------------------------------- //

const uuidSchema = z.string().uuid({ message: "Invalid ID format" });

const isoDateSchema = z
  .string()
  .datetime({ message: "Invalid date format" });

const emailSchema = z
  .string()
  .min(1, { message: "Email is required" })
  .email({ message: "Please enter a valid email address" })
  .toLowerCase()
  .trim();

const newPasswordSchema = z
  .string()
  .min(8,  { message: "Password must be at least 8 characters" })
  .max(128, { message: "Password is too long" })
  .regex(/[A-Z]/, { message: "Password must contain at least one uppercase letter" })
  .regex(/[a-z]/, { message: "Password must contain at least one lowercase letter" })
  .regex(/[0-9]/, { message: "Password must contain at least one number" });

const urlSchema = z
  .string()
  .url({ message: "Please enter a valid URL" })
  .refine(
    (u) => u.startsWith("http://") || u.startsWith("https://"),
    { message: "URL must start with http:// or https://" }
  );

const gcsUrlSchema = z
  .string()
  .url({ message: "Invalid file URL" })
  .refine(
    (u) => u.startsWith("https://storage.googleapis.com/"),
    { message: "Invalid upload URL. Please re-upload your file." }
  );

const subjectSchema = z.enum(
  Object.values(SUBJECTS) as [string, ...string[]],
  { errorMap: () => ({ message: "Please select a valid subject" }) }
);

const curriculumSchema = z.enum(
  Object.values(CURRICULA) as [string, ...string[]],
  { errorMap: () => ({ message: "Please select a valid curriculum" }) }
);

const difficultySchema = z.enum(
  Object.values(DIFFICULTY_LEVELS) as [string, ...string[]],
  { errorMap: () => ({ message: "Please select a difficulty level" }) }
);

const languageSchema = z.enum(
  Object.values(LANGUAGES) as [string, ...string[]],
  { errorMap: () => ({ message: "Please select a supported language" }) }
);

const starRatingSchema = z
  .number()
  .int({ message: "Rating must be a whole number" })
  .min(1, { message: "Rating must be at least 1 star" })
  .max(5, { message: "Rating cannot exceed 5 stars" });

const sceneIndexSchema = z
  .number()
  .int({ message: "Scene index must be a whole number" })
  .min(0, { message: "Scene index cannot be negative" })
  .max(7, { message: "Scene index cannot exceed 7 (max 8 scenes)" })
  .nullable();

// -------------------------------------------------------------------------- //
// Auth schemas                                                                  //
// -------------------------------------------------------------------------- //

/**
 * Login form schema.
 * Maps to: POST /auth/token (OAuth2 password flow).
 * Password validation is intentionally loose — user may have an older password.
 */
export const LoginSchema = z
  .object({
    email: emailSchema,
    password: z.string().min(1, { message: "Password is required" }),
    rememberMe: z.boolean().default(false),
  })
  .strip();

export type LoginFormValues = z.infer<typeof LoginSchema>;

/**
 * Registration form schema.
 * Maps to: POST /auth/register.
 * Enforces strong password + confirmation match + ToS acceptance.
 */
export const RegisterSchema = z
  .object({
    email: emailSchema,
    fullName: z
      .string()
      .trim()
      .min(2, { message: "Name must be at least 2 characters" })
      .max(100, { message: "Name must be less than 100 characters" })
      .optional()
      .or(z.literal("")),
    password: newPasswordSchema,
    confirmPassword: z
      .string()
      .min(1, { message: "Please confirm your password" }),
    acceptTerms: z.literal(true, {
      errorMap: () => ({
        message: "You must accept the Terms of Service to continue",
      }),
    }),
  })
  .strip()
  .refine((d) => d.password === d.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

export type RegisterFormValues = z.infer<typeof RegisterSchema>;

/**
 * Forgot password form schema.
 * Only email — backend sends a reset link.
 */
export const ForgotPasswordSchema = z
  .object({ email: emailSchema })
  .strip();

export type ForgotPasswordFormValues = z.infer<typeof ForgotPasswordSchema>;

/**
 * Reset password form schema.
 * Token comes from the URL query param, not a form field.
 */
export const ResetPasswordSchema = z
  .object({
    password: newPasswordSchema,
    confirmPassword: z
      .string()
      .min(1, { message: "Please confirm your new password" }),
  })
  .strip()
  .refine((d) => d.password === d.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

export type ResetPasswordFormValues = z.infer<typeof ResetPasswordSchema>;

// -------------------------------------------------------------------------- //
// Project schemas                                                               //
// -------------------------------------------------------------------------- //

/**
 * Project creation form schema.
 * Maps to: POST /api/v1/jobs/create → CreateProjectRequest.
 *
 * Rules:
 *   - Title: 3–200 chars
 *   - Subject, curriculum, difficulty, language: valid enum values
 *   - At least one of inputText (≥ 20 chars) or inputImageUrl must be provided
 *   - Tier restrictions are NOT enforced here — handled by backend + UI gates
 */
export const CreateProjectSchema = z
  .object({
    title: z
      .string()
      .trim()
      .min(3,   { message: "Title must be at least 3 characters" })
      .max(200, { message: "Title must be less than 200 characters" }),
    subject:        subjectSchema.optional(),
    curriculum:     curriculumSchema.optional(),
    difficultyLevel: difficultySchema.default("intermediate"),
    language:       languageSchema.default("en"),
    inputText:      z.string().trim().optional().or(z.literal("")),
    inputImageUrl:  z.string().url().optional().nullable(),
  })
  .strip()
  .refine(
    (d) => {
      const hasText  = (d.inputText?.trim().length ?? 0) >= 20;
      const hasImage = Boolean(d.inputImageUrl?.trim().length);
      return hasText || hasImage;
    },
    {
      message:
        "Please provide either a text description (at least 20 characters) or upload an image",
      path: ["inputText"],
    }
  )
  .refine(
    (d) => {
      const len = d.inputText?.trim().length ?? 0;
      return len === 0 || len >= 20;
    },
    {
      message:
        "Your description is too short. Please add more detail (at least 20 characters)",
      path: ["inputText"],
    }
  );

export type CreateProjectFormValues = z.infer<typeof CreateProjectSchema>;

/**
 * Project list filter schema.
 * Used by the projects page filter controls.
 */
export const ProjectFilterSchema = z
  .object({
    status: z
      .enum([
        "pending", "queued", "orchestrating", "rendering",
        "review", "done", "failed", "cancelled",
      ])
      .optional(),
    subject: subjectSchema.optional(),
    page:    z.number().int().min(1).default(1),
    limit:   z.number().int().min(1).max(50).default(20),
  })
  .strip();

export type ProjectFilterValues = z.infer<typeof ProjectFilterSchema>;

// -------------------------------------------------------------------------- //
// Feedback schemas                                                              //
// -------------------------------------------------------------------------- //

/**
 * Feedback submission form schema.
 * Maps to: POST /api/v1/feedback/{job_id}.
 *
 * Business rules:
 *   - incorrect_content → comment REQUIRED (reviewer needs specifics)
 *   - curriculum_mismatch → comment REQUIRED
 *   - audio_issue / poor_animation → sceneIndex strongly recommended (soft warning)
 */
export const FeedbackSchema = z
  .object({
    feedbackType: z.enum(
      Object.values(FEEDBACK_TYPES) as [string, ...string[]],
      { errorMap: () => ({ message: "Please select a feedback type" }) }
    ),
    sceneIndex: sceneIndexSchema.default(null),
    rating:     starRatingSchema.optional().nullable(),
    comment: z
      .string()
      .trim()
      .min(10,   { message: "Please add more detail (at least 10 characters)" })
      .max(1000, { message: "Comment is too long (maximum 1000 characters)" })
      .optional()
      .or(z.literal("")),
  })
  .strip()
  .refine(
    (d) => {
      if (d.feedbackType === "incorrect_content" || d.feedbackType === "curriculum_mismatch") {
        return (d.comment?.trim().length ?? 0) >= 10;
      }
      return true;
    },
    {
      message: "Please describe the issue in detail so our team can fix it",
      path: ["comment"],
    }
  );

export type FeedbackFormValues = z.infer<typeof FeedbackSchema>;

/**
 * Quick star rating schema — post-generation prompt (no full feedback form).
 */
export const QuickRatingSchema = z
  .object({
    rating: starRatingSchema,
    jobId:  uuidSchema,
  })
  .strip();

export type QuickRatingValues = z.infer<typeof QuickRatingSchema>;

// -------------------------------------------------------------------------- //
// Review schemas (admin-only)                                                   //
// -------------------------------------------------------------------------- //

const REJECTION_REASONS_VALUES = [
  "factual_error",
  "curriculum_mismatch",
  "poor_quality",
  "inappropriate_content",
  "other",
] as const;

const REVIEW_PRIORITIES_VALUES = [
  "low", "normal", "high", "urgent",
] as const;

const TRIGGER_REASONS_VALUES = [
  "new_subject",
  "low_confidence",
  "flagged_content",
  "user_reported",
  "curriculum_mismatch",
  "high_cost_anomaly",
  "manual",
] as const;

/**
 * Reviewer decision form schema.
 * Maps to: POST /api/v1/review/{review_id}/decision.
 *
 * Business rules:
 *   - reject → rejectionReason REQUIRED
 *   - requires_revision → reviewerNotes REQUIRED (≥ 10 chars)
 *   - correctionApplied=true → correctionNotes REQUIRED (≥ 10 chars)
 */
export const ApprovalSchema = z
  .object({
    action: z.enum(["approve", "reject", "requires_revision"], {
      errorMap: () => ({ message: "Please select an action" }),
    }),
    reviewerNotes: z
      .string()
      .trim()
      .max(2000, { message: "Notes must be less than 2000 characters" })
      .optional()
      .or(z.literal("")),
    rejectionReason: z
      .enum(REJECTION_REASONS_VALUES, {
        errorMap: () => ({ message: "Please select a rejection reason" }),
      })
      .optional()
      .nullable(),
    correctionApplied: z.boolean().default(false),
    correctionNotes: z
      .string()
      .trim()
      .min(10,   { message: "Please describe what was corrected (at least 10 characters)" })
      .max(2000, { message: "Correction notes must be less than 2000 characters" })
      .optional()
      .or(z.literal("")),
  })
  .strip()
  .refine(
    (d) => d.action !== "reject" || Boolean(d.rejectionReason),
    { message: "Please select a reason for rejection", path: ["rejectionReason"] }
  )
  .refine(
    (d) => d.action !== "requires_revision" || (d.reviewerNotes?.trim().length ?? 0) >= 10,
    {
      message: "Please explain what revisions are needed (at least 10 characters)",
      path: ["reviewerNotes"],
    }
  )
  .refine(
    (d) => !d.correctionApplied || (d.correctionNotes?.trim().length ?? 0) >= 10,
    {
      message: "Please describe the correction you applied",
      path: ["correctionNotes"],
    }
  );

export type ApprovalFormValues = z.infer<typeof ApprovalSchema>;

/**
 * Review queue filter schema — admin review queue page.
 */
export const ReviewQueueFilterSchema = z
  .object({
    priority:      z.enum(REVIEW_PRIORITIES_VALUES).optional(),
    triggerReason: z.enum(TRIGGER_REASONS_VALUES).optional(),
    limit:         z.number().int().min(1).max(100).default(20),
  })
  .strip();

export type ReviewQueueFilterValues = z.infer<typeof ReviewQueueFilterSchema>;

// -------------------------------------------------------------------------- //
// Billing schemas                                                               //
// -------------------------------------------------------------------------- //

/**
 * Payment method setup schema.
 * Stripe card details are validated by Stripe Elements — not here.
 * This validates the form wrapper (name on card + billing terms).
 */
export const PaymentMethodSchema = z
  .object({
    savePaymentMethod: z.boolean().default(true),
    billingName: z
      .string()
      .trim()
      .min(2,   { message: "Please enter the name on your card" })
      .max(100, { message: "Name is too long" }),
    acceptBillingTerms: z.literal(true, {
      errorMap: () => ({ message: "Please accept the billing terms to continue" }),
    }),
  })
  .strip();

export type PaymentMethodFormValues = z.infer<typeof PaymentMethodSchema>;

/**
 * Stripe Checkout initiation schema.
 * Validates redirect URLs before creating a checkout session.
 */
export const CheckoutSchema = z
  .object({
    successUrl: urlSchema,
    cancelUrl:  urlSchema,
  })
  .strip();

export type CheckoutFormValues = z.infer<typeof CheckoutSchema>;

/**
 * Subscription cancellation confirmation schema.
 * User must type "CANCEL" to confirm — prevents accidental cancellation.
 */
export const CancelSubscriptionSchema = z
  .object({
    cancelImmediately: z.boolean().default(false),
    confirmText: z.string().trim(),
    reason: z
      .string()
      .trim()
      .max(500, { message: "Reason must be less than 500 characters" })
      .optional()
      .or(z.literal("")),
  })
  .strip()
  .refine(
    (d) => d.confirmText === "CANCEL",
    { message: 'Please type "CANCEL" to confirm cancellation', path: ["confirmText"] }
  );

export type CancelSubscriptionFormValues = z.infer<typeof CancelSubscriptionSchema>;

// -------------------------------------------------------------------------- //
// Profile / Account schemas                                                     //
// -------------------------------------------------------------------------- //

/**
 * Profile update schema.
 * Maps to: PATCH /api/v1/users/me.
 * All fields optional — only changed fields need to be sent.
 */
export const UpdateProfileSchema = z
  .object({
    fullName: z
      .string()
      .trim()
      .min(2,   { message: "Name must be at least 2 characters" })
      .max(100, { message: "Name must be less than 100 characters" })
      .optional()
      .or(z.literal("")),
    preferredLanguage: languageSchema.optional(),
    preferredCurriculum: curriculumSchema.optional(),
  })
  .strip();

export type UpdateProfileFormValues = z.infer<typeof UpdateProfileSchema>;

/**
 * Change password schema (for authenticated users in settings).
 * Requires current password for verification.
 */
export const ChangePasswordSchema = z
  .object({
    currentPassword: z
      .string()
      .min(1, { message: "Current password is required" }),
    newPassword: newPasswordSchema,
    confirmNewPassword: z
      .string()
      .min(1, { message: "Please confirm your new password" }),
  })
  .strip()
  .refine(
    (d) => d.newPassword === d.confirmNewPassword,
    { message: "Passwords do not match", path: ["confirmNewPassword"] }
  )
  .refine(
    (d) => d.currentPassword !== d.newPassword,
    {
      message: "New password must be different from your current password",
      path: ["newPassword"],
    }
  );

export type ChangePasswordFormValues = z.infer<typeof ChangePasswordSchema>;

// -------------------------------------------------------------------------- //
// Helper utilities                                                              //
// -------------------------------------------------------------------------- //

/**
 * Format a ZodError into a flat record of field → first error message.
 * Use this to map Zod validation errors onto React Hook Form field errors
 * when calling validate() outside of zodResolver.
 *
 * @param error - ZodError from schema.safeParse()
 * @returns Record mapping field path string to first error message
 *
 * @example
 *   const result = LoginSchema.safeParse(input);
 *   if (!result.success) {
 *     const errors = formatZodError(result.error);
 *     // { email: "Please enter a valid email address", ... }
 *   }
 */
export function formatZodError(
  error: z.ZodError
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const issue of error.issues) {
    const path = issue.path.join(".");
    if (path && !out[path]) {
      out[path] = issue.message;
    }
  }
  return out;
}

/**
 * Safely parse input through a schema and return typed result.
 * Returns { data, errors } — never throws.
 * Use instead of schema.parse() when you want to handle errors gracefully.
 *
 * @param schema - Any Zod schema
 * @param input - Raw unvalidated input
 * @returns { data: T | null, errors: Record<string, string> | null }
 *
 * @example
 *   const { data, errors } = safeValidate(LoginSchema, formValues);
 *   if (errors) showFieldErrors(errors);
 *   else await login(data.email, data.password);
 */
export function safeValidate<T>(
  schema: z.ZodSchema<T>,
  input: unknown
): { data: T | null; errors: Record<string, string> | null } {
  const result = schema.safeParse(input);
  if (result.success) {
    return { data: result.data, errors: null };
  }
  return { data: null, errors: formatZodError(result.error) };
}

/**
 * Get the first error message for a specific field from a ZodError.
 * Convenience function for inline field validation display.
 *
 * @param error - ZodError from schema.safeParse()
 * @param fieldPath - Dot-separated field path e.g. "email" or "address.city"
 * @returns First error message for that field, or undefined if no error
 *
 * @example
 *   const msg = getFieldError(result.error, "confirmPassword");
 *   // "Passwords do not match"
 */
export function getFieldError(
  error: z.ZodError,
  fieldPath: string
): string | undefined {
  return error.issues.find(
    (issue) => issue.path.join(".") === fieldPath
  )?.message;
}

// -------------------------------------------------------------------------- //
// Re-export primitives for use in custom schemas outside this file             //
// -------------------------------------------------------------------------- //

export {
  uuidSchema,
  isoDateSchema,
  emailSchema,
  newPasswordSchema,
  urlSchema,
  gcsUrlSchema,
  subjectSchema,
  curriculumSchema,
  difficultySchema,
  languageSchema,
  starRatingSchema,
  sceneIndexSchema,
};
