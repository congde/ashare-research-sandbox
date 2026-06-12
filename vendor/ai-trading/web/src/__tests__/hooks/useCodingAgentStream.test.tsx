/**
 * Unit tests for the coding-agent WebSocket streaming hook
 * (RFC 0002 §3.3.12.5 / TIER 3D).
 *
 * The hook owns a single WS connection per session_id, parses
 * v1-envelope frames, exposes the running list of items, the latest
 * seq cursor for resume, and a connection state ('connecting' |
 * 'open' | 'closed' | 'error'). On close it auto-reconnects with
 * the cursor it had so the user never sees gaps after a transient
 * network blip.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  useCodingAgentStream,
} from "../../hooks/useCodingAgentStream";

// ── In-memory WebSocket double ──────────────────────────────────


interface Envelope {
  schema: string;
  session_id: string;
  seq: number;
  turn_seq: number;
  kind: string;
  payload: Record<string, unknown>;
  ts: string;
}

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  readyState: number = 0; // CONNECTING
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  closed = false;
  closeCode?: number;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  // ── simulator helpers (called by tests) ──
  open() {
    this.readyState = 1; // OPEN
    this.onopen?.(new Event("open"));
  }

  emit(env: Envelope) {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(env) }),
    );
  }

  emitRaw(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  remoteClose(code = 1000) {
    this.readyState = 3; // CLOSED
    this.closeCode = code;
    this.onclose?.(new CloseEvent("close", { code }));
  }

  close() {
    this.closed = true;
    this.readyState = 3;
  }
}


function envelope(overrides: Partial<Envelope> = {}): Envelope {
  return {
    schema: "v1",
    session_id: "00000000-0000-0000-0000-000000000001",
    seq: 1,
    turn_seq: 1,
    kind: "user_msg",
    payload: { text: "hello" },
    ts: new Date().toISOString(),
    ...overrides,
  };
}


// ── Test setup / teardown ───────────────────────────────────────


beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  // Stub localStorage token retrieval
  vi.spyOn(Storage.prototype, "getItem").mockImplementation((key) =>
    key === "de_token" ? "fake-token" : null,
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


// ── Connection lifecycle ────────────────────────────────────────


describe("useCodingAgentStream", () => {
  it("opens a WS to the right URL with auth token", () => {
    renderHook(() => useCodingAgentStream("00000000-0000-0000-0000-000000000001"));

    expect(FakeWebSocket.instances).toHaveLength(1);
    const ws = FakeWebSocket.instances[0];
    expect(ws.url).toContain("/ws/coding-agent/00000000-0000-0000-0000-000000000001");
    expect(ws.url).toContain("token=fake-token");
    expect(ws.url).toContain("after_seq=0");
  });

  it("uses initialAfterSeq as the resume cursor", () => {
    renderHook(() =>
      useCodingAgentStream(
        "00000000-0000-0000-0000-000000000001",
        { initialAfterSeq: 142 },
      ),
    );
    const ws = FakeWebSocket.instances[0];
    expect(ws.url).toContain("after_seq=142");
  });

  it("reports 'connecting' state before open", () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001"),
    );
    expect(result.current.status).toBe("connecting");
  });

  it("transitions to 'open' on socket open", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001"),
    );
    const ws = FakeWebSocket.instances[0];
    act(() => {
      ws.open();
    });
    await waitFor(() => expect(result.current.status).toBe("open"));
  });

  it("appends incoming envelopes to items", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001"),
    );
    const ws = FakeWebSocket.instances[0];
    act(() => {
      ws.open();
    });
    act(() => {
      ws.emit(envelope({ seq: 1, kind: "user_msg" }));
      ws.emit(envelope({ seq: 2, kind: "assistant_msg" }));
    });
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.items[0].seq).toBe(1);
    expect(result.current.items[1].kind).toBe("assistant_msg");
  });

  it("advances the seq cursor as items arrive", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001"),
    );
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    act(() => {
      ws.emit(envelope({ seq: 5 }));
      ws.emit(envelope({ seq: 7 }));
    });
    await waitFor(() => expect(result.current.cursor).toBe(7));
  });

  it("ignores envelopes with unknown schema version", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001"),
    );
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    act(() => {
      ws.emit(envelope({ seq: 1 }));
      ws.emit(envelope({ seq: 2, schema: "v99" }));
      ws.emit(envelope({ seq: 3 }));
    });
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    expect(result.current.items.map((i) => i.seq)).toEqual([1, 3]);
  });

  it("ignores malformed JSON frames without crashing", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001"),
    );
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    act(() => {
      ws.emitRaw("not-valid-json");
      ws.emit(envelope({ seq: 1 }));
    });
    await waitFor(() => expect(result.current.items).toHaveLength(1));
  });

  it("transitions to 'closed' on remote close", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001", {
        autoReconnect: false,
      }),
    );
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.remoteClose());
    await waitFor(() => expect(result.current.status).toBe("closed"));
  });

  it("auto-reconnects with the latest cursor after close", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001", {
        autoReconnect: true,
        reconnectDelayMs: 0,
      }),
    );
    const ws1 = FakeWebSocket.instances[0];
    act(() => ws1.open());
    act(() => {
      ws1.emit(envelope({ seq: 42 }));
    });
    await waitFor(() => expect(result.current.cursor).toBe(42));

    act(() => ws1.remoteClose(1011));
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2));
    const ws2 = FakeWebSocket.instances[1];
    expect(ws2.url).toContain("after_seq=42");
  });

  it("closes the socket on unmount", () => {
    const { unmount } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001"),
    );
    const ws = FakeWebSocket.instances[0];
    expect(ws.closed).toBe(false);
    unmount();
    expect(ws.closed).toBe(true);
  });

  it("does not reconnect on intentional close (4001 / 4404)", async () => {
    const { result } = renderHook(() =>
      useCodingAgentStream("00000000-0000-0000-0000-000000000001", {
        autoReconnect: true,
        reconnectDelayMs: 0,
      }),
    );
    const ws = FakeWebSocket.instances[0];
    act(() => ws.open());
    act(() => ws.remoteClose(4001)); // auth fail
    await waitFor(() => expect(result.current.status).toBe("error"));
    // Should NOT reconnect — auth failure is permanent
    await new Promise((r) => setTimeout(r, 20));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
