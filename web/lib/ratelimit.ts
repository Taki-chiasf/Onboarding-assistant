import { NextRequest } from "next/server";

/**
 * Fixed-window per-client rate limiter for the BFF.
 *
 * The demo has no reverse proxy with a limiter in front, so the BFF enforces a
 * basic per-IP allowance: a per-minute cap on chat turns, a stricter one on
 * auth endpoints. State lives per process — appropriate for the demo's
 * single-instance deployment, and fail-open by nature: a full in-memory
 * window evicts lazily rather than blocking.
 */

type Bucket = { count: number; resetAt: number };

type RateLimitDecision =
  | { ok: true }
  | { ok: false; retryAfterS: number };

/**
 * Count a request against `key` and slide the fixed window when it expires.
 * Exposed with an injectable clock for tests.
 */
export function checkLimit(
  key: string,
  limit: number,
  windowMs: number,
  clock: () => number
): RateLimitDecision {
  const state = limitState();
  const now = clock();
  if (state.size > 10_000) {
    for (const [k, bucket] of state) {
      if (bucket.resetAt <= now) state.delete(k);
    }
  }
  const bucket = state.get(key);
  if (!bucket || bucket.resetAt <= now) {
    state.set(key, { count: 1, resetAt: now + windowMs });
    return { ok: true };
  }
  bucket.count += 1;
  if (bucket.count > limit) {
    return { ok: false, retryAfterS: Math.max(1, Math.ceil((bucket.resetAt - now) / 1000)) };
  }
  return { ok: true };
}

function limitState(): Map<string, Bucket> {
  const holder = globalThis as typeof globalThis & {
    __rateLimitBuckets?: Map<string, Bucket>;
  };
  // Survive dev hot reloads by hanging the map off globalThis.
  holder.__rateLimitBuckets ??= new Map<string, Bucket>();
  return holder.__rateLimitBuckets;
}

/** Fixed-window limit, checked with the wall clock. */
export function rateLimit(key: string, limit: number, windowMs: number): RateLimitDecision {
  return checkLimit(key, limit, windowMs, () => Date.now());
}

/** The client's best-effort source address, as BFF routes see it. */
export function clientKey(request: NextRequest): string {
  const forwarded = request.headers.get("x-forwarded-for");
  const first = forwarded?.split(",")[0]?.trim();
  return first || request.headers.get("x-real-ip") || "unknown";
}

/** Rate limits for the two BFF surfaces that can cost money. */
export const LIMITS = {
  /** Chat turns per minute per client. */
  chat: { limit: 20, windowMs: 60_000 },
  /** Login/auth attempts per 10 minutes per client — persona switches are rare. */
  auth: { limit: 30, windowMs: 10 * 60_000 },
} as const;

/** Plain-text response for a limited request. */
export function limitedResponse(retryAfterS: number): Response {
  return new Response("rate limited", {
    status: 429,
    headers: { "retry-after": String(retryAfterS), "content-type": "text/plain" },
  });
}
