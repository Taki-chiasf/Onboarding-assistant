import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { checkLimit, clientKey, LIMITS } from "./ratelimit";

describe("checkLimit", () => {
  it("admits requests up to the limit within the window", () => {
    const now = 0;
    for (let i = 0; i < LIMITS.chat.limit; i++) {
      expect(checkLimit("ip-a", LIMITS.chat.limit, LIMITS.chat.windowMs, () => now)).toEqual({
        ok: true,
      });
    }
    expect(checkLimit("ip-a", LIMITS.chat.limit, LIMITS.chat.windowMs, () => now)).toEqual({
      ok: false,
      retryAfterS: LIMITS.chat.windowMs / 1000,
    });
  });

  it("resets after the window elapses", () => {
    let now = 0;
    const limit = 2;
    checkLimit("ip-b", limit, 1000, () => now);
    checkLimit("ip-b", limit, 1000, () => now);
    expect(checkLimit("ip-b", limit, 1000, () => now)).toEqual({
      ok: false,
      retryAfterS: 1,
    });
    now = 1001;
    expect(checkLimit("ip-b", limit, 1000, () => now)).toEqual({ ok: true });
  });

  it("tracks clients independently", () => {
    const now = 0;
    checkLimit("ip-c", 1, 60_000, () => now);
    expect(checkLimit("ip-c", 1, 60_000, () => now)).toEqual({ ok: false, retryAfterS: 60 });
    expect(checkLimit("ip-d", 1, 60_000, () => now)).toEqual({ ok: true });
  });

  it("caps the retry window at one second minimum", () => {
    const now = 500;
    checkLimit("ip-e", 1, 1000, () => 0);
    expect(checkLimit("ip-e", 1, 1000, () => now)).toEqual({ ok: false, retryAfterS: 1 });
  });
});

describe("clientKey", () => {
  function requestWith(headers: Record<string, string>): NextRequest {
    return new NextRequest("http://localhost/api/chat", { headers });
  }

  it("prefers the first x-forwarded-for hop", () => {
    const request = requestWith({ "x-forwarded-for": "203.0.113.7, 10.0.0.1" });
    expect(clientKey(request)).toBe("203.0.113.7");
  });

  it("falls back to x-real-ip, then unknown", () => {
    expect(clientKey(requestWith({ "x-real-ip": "198.51.100.3" }))).toBe("198.51.100.3");
    expect(clientKey(requestWith({}))).toBe("unknown");
  });
});
