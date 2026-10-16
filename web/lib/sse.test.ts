import { describe, expect, it } from "vitest";

import { readSse, sseBody } from "./sse";

describe("readSse", () => {
  it("relays event names with parsed payloads", async () => {
    const events: [string, Record<string, unknown>][] = [];
    await readSse(
      sseBody([
        'event: sources\ndata: {"conversation_id": "c1"}\n\n',
        'event: token\ndata: {"text": "16 "}\n\n',
      ]),
      (event, data) => events.push([event, data])
    );
    expect(events).toEqual([
      ["sources", { conversation_id: "c1" }],
      ["token", { text: "16 " }],
    ]);
  });

  it("ignores keepalive comment frames", async () => {
    const events: [string, Record<string, unknown>][] = [];
    await readSse(
      sseBody([': keepalive\n\n', 'event: token\ndata: {"text": "x"}\n\n', ': keepalive\n\n']),
      (event, data) => events.push([event, data])
    );
    expect(events).toEqual([["token", { text: "x" }]]);
  });

  it("assembles frames split across chunk boundaries", async () => {
    const events: [string, Record<string, unknown>][] = [];
    const encoder = new TextEncoder();
    const parts = [
      'event: done\nda',
      'ta: {"answer": "yes"}\n\n',
    ];
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const part of parts) controller.enqueue(encoder.encode(part));
        controller.close();
      },
    });
    await readSse(body, (event, data) => events.push([event, data]));
    expect(events).toEqual([["done", { answer: "yes" }]]);
  });

  it("skips malformed payloads without killing the stream", async () => {
    const events: [string, Record<string, unknown>][] = [];
    await readSse(
      sseBody(['event: token\ndata: {oops\n\n', 'event: token\ndata: {"text": "ok"}\n\n']),
      (event, data) => events.push([event, data])
    );
    expect(events).toEqual([["token", { text: "ok" }]]);
  });
});
