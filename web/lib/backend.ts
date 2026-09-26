import { NextResponse } from "next/server";

export function backendUrl(): string {
  return process.env.BACKEND_URL ?? "http://localhost:8000";
}

/**
 * Copy the backend's session cookie onto a browser-facing response. The web app
 * holds the session cookie; the backend trusts the value the BFF forwards.
 */
export function copySessionCookie(source: Response, response: NextResponse): void {
  const setCookie = source.headers.get("set-cookie");
  if (!setCookie) return;
  const [pair] = setCookie.split(";");
  const [name, value] = pair.split("=");
  response.cookies.set(name, value, { httpOnly: true, sameSite: "lax", path: "/" });
}
