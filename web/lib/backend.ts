export function backendUrl(): string {
  return process.env.BACKEND_URL ?? "http://localhost:8000";
}
