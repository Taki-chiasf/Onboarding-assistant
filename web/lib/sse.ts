/**
 * Minimal SSE frame parser for the chat stream.
 *
 * Relays `event: <name>` + `data: <json>` frames to a callback. Comment lines
 * (`: keepalive`) carry no data and are ignored, as are malformed payloads —
 * a backend that speaks SSE composes fine with any quiet gap it inserts.
 */
export async function readSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: string, data: Record<string, unknown>) => void
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      let event = "message";
      let data = "";
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice("event: ".length).trim();
        else if (line.startsWith("data: ")) data += line.slice("data: ".length);
      }
      if (!data) continue; // comment frame
      try {
        onEvent(event, JSON.parse(data) as Record<string, unknown>);
      } catch {
        /* ignore malformed frame */
      }
    }
  }
}

/** Build a hand-crafted SSE body for tests. */
export function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      controller.close();
    },
  });
}
