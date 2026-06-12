/**
 * Tests for the useResearchStream hook.
 *
 * Hook flow under test:
 *   1. Mount → POST /research/stream/start
 *   2. Open WS → send {action:"subscribe", room}
 *   3. Receive `subscribed` ack → status:"connected"
 *   4. Receive `research_stream` message → push into events buffer
 *   5. Unmount → unsubscribe + close WS + POST /research/stream/stop
 *
 * WebSocket is mocked at the global level. The test triggers
 * server-pushed messages by calling the mock's `simulateMessage()`.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";

// Mock the API client BEFORE the hook imports it.
vi.mock("../../api/services", () => ({
  researchStreamApi: {
    start: vi.fn(),
    stop: vi.fn(),
    list: vi.fn(),
  },
}));

import { researchStreamApi } from "../../api/services";
import { useResearchStream } from "../../hooks/useResearchStream";

// ── Mock WebSocket ────────────────────────────────────────────

interface MockWebSocketInstance {
  url: string;
  readyState: number;
  sent: string[];
  listeners: Record<string, ((ev: unknown) => void)[]>;
  send: (data: string) => void;
  close: () => void;
  addEventListener: (event: string, cb: (ev: unknown) => void) => void;
  removeEventListener: (event: string, cb: (ev: unknown) => void) => void;
  // Test helpers
  simulateOpen: () => void;
  simulateMessage: (data: string) => void;
  simulateClose: () => void;
}

const wsInstances: MockWebSocketInstance[] = [];

class MockWebSocket implements MockWebSocketInstance {
  static OPEN = 1;
  static CLOSED = 3;
  static CONNECTING = 0;

  url: string;
  readyState: number = MockWebSocket.CONNECTING;
  sent: string[] = [];
  listeners: Record<string, ((ev: unknown) => void)[]> = {};

  constructor(url: string) {
    this.url = url;
    wsInstances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.readyState = MockWebSocket.CLOSED;
    this.simulateClose();
  }

  addEventListener(event: string, cb: (ev: unknown) => void): void {
    (this.listeners[event] = this.listeners[event] || []).push(cb);
  }

  removeEventListener(event: string, cb: (ev: unknown) => void): void {
    if (this.listeners[event]) {
      this.listeners[event] = this.listeners[event].filter((x) => x !== cb);
    }
  }

  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN;
    (this.listeners.open || []).forEach((cb) => cb({}));
  }

  simulateMessage(data: string): void {
    (this.listeners.message || []).forEach((cb) =>
      cb({ data } as MessageEvent<string>),
    );
  }

  simulateClose(): void {
    (this.listeners.close || []).forEach((cb) => cb({}));
  }
}

// ── Test setup ────────────────────────────────────────────────

const originalWebSocket = globalThis.WebSocket;

describe("useResearchStream", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    wsInstances.length = 0;
    // Replace global WebSocket with our mock
    (globalThis as { WebSocket: typeof WebSocket }).WebSocket =
      MockWebSocket as unknown as typeof WebSocket;

    // Default mock responses
    (researchStreamApi.start as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: {
        room_name: "research-stream:market",
        channel_path: "/stream/market/subscribe",
        query_params: null,
        created: true,
        metrics: {
          events_received: 0,
          events_published: 0,
          reconnects: 0,
          last_event_at: null,
          last_error: null,
        },
      },
    });
    (researchStreamApi.stop as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { room_name: "research-stream:market", stopped: true },
    });
  });

  afterEach(() => {
    (globalThis as { WebSocket: typeof WebSocket }).WebSocket = originalWebSocket;
  });

  it("calls /research/stream/start on mount", async () => {
    renderHook(() => useResearchStream());
    await waitFor(() => {
      expect(researchStreamApi.start).toHaveBeenCalledWith({
        channel: "/stream/market/subscribe",
        query_params: null,
      });
    });
  });

  it("transitions through starting → subscribing → connected", async () => {
    const { result } = renderHook(() => useResearchStream());

    // After start API resolves, the WS is constructed and opened.
    await waitFor(() => {
      expect(wsInstances.length).toBe(1);
    });

    act(() => {
      wsInstances[0].simulateOpen();
    });
    expect(result.current.status).toBe("subscribing");

    // The hook sent a subscribe action
    expect(wsInstances[0].sent[0]).toContain('"action":"subscribe"');
    expect(wsInstances[0].sent[0]).toContain('"room":"research-stream:market"');

    // Server acks the subscribe → connected
    act(() => {
      wsInstances[0].simulateMessage(
        JSON.stringify({
          action: "subscribed",
          room: "research-stream:market",
        }),
      );
    });

    expect(result.current.status).toBe("connected");
    expect(result.current.error).toBeNull();
  });

  it("pushes research_stream events into the buffer", async () => {
    const { result } = renderHook(() => useResearchStream());

    await waitFor(() => {
      expect(wsInstances.length).toBe(1);
    });

    act(() => {
      wsInstances[0].simulateOpen();
      wsInstances[0].simulateMessage(
        JSON.stringify({ action: "subscribed", room: "research-stream:market" }),
      );
    });

    act(() => {
      wsInstances[0].simulateMessage(
        JSON.stringify({
          type: "research_stream",
          channel_path: "/stream/market/subscribe",
          payload: {
            event: "market_analysis",
            data: '{"trend":"bullish"}',
            retry: null,
          },
          timestamp: "2026-05-17T08:00:00Z",
        }),
      );
    });

    expect(result.current.events.length).toBe(1);
    expect(result.current.events[0].event).toBe("market_analysis");
    expect(result.current.events[0].data).toBe('{"trend":"bullish"}');
  });

  it("clears the buffer when clear() is called", async () => {
    const { result } = renderHook(() => useResearchStream());

    await waitFor(() => {
      expect(wsInstances.length).toBe(1);
    });

    act(() => {
      wsInstances[0].simulateOpen();
      wsInstances[0].simulateMessage(
        JSON.stringify({ action: "subscribed", room: "research-stream:market" }),
      );
      wsInstances[0].simulateMessage(
        JSON.stringify({
          type: "research_stream",
          payload: { event: "x", data: "y", retry: null },
        }),
      );
    });

    expect(result.current.events.length).toBe(1);

    act(() => {
      result.current.clear();
    });

    expect(result.current.events.length).toBe(0);
  });

  it("caps the event buffer at maxEvents", async () => {
    const { result } = renderHook(() => useResearchStream({ maxEvents: 3 }));

    await waitFor(() => {
      expect(wsInstances.length).toBe(1);
    });

    act(() => {
      wsInstances[0].simulateOpen();
      wsInstances[0].simulateMessage(
        JSON.stringify({ action: "subscribed", room: "research-stream:market" }),
      );
    });

    // Push 5 events
    act(() => {
      for (let i = 0; i < 5; i++) {
        wsInstances[0].simulateMessage(
          JSON.stringify({
            type: "research_stream",
            payload: { event: "x", data: String(i), retry: null },
          }),
        );
      }
    });

    expect(result.current.events.length).toBe(3);
    // Oldest dropped — buffer holds last 3
    expect(result.current.events.map((e) => e.data)).toEqual(["2", "3", "4"]);
  });

  it("surfaces an API error", async () => {
    (researchStreamApi.start as ReturnType<typeof vi.fn>).mockRejectedValue({
      response: { data: { detail: "DexScan upstream broken" } },
    });

    const { result } = renderHook(() => useResearchStream());

    await waitFor(() => {
      expect(result.current.status).toBe("error");
    });
    expect(result.current.error).toContain("DexScan upstream broken");
  });

  it("calls /research/stream/stop on unmount", async () => {
    const { unmount } = renderHook(() => useResearchStream());

    await waitFor(() => {
      expect(wsInstances.length).toBe(1);
    });
    act(() => {
      wsInstances[0].simulateOpen();
      wsInstances[0].simulateMessage(
        JSON.stringify({ action: "subscribed", room: "research-stream:market" }),
      );
    });

    unmount();

    await waitFor(() => {
      expect(researchStreamApi.stop).toHaveBeenCalledWith({
        room_name: "research-stream:market",
      });
    });
  });

  it("does not connect when enabled is false", async () => {
    const { result } = renderHook(() =>
      useResearchStream({ enabled: false }),
    );

    // Give async path a tick to confirm it did NOT run.
    await new Promise((resolve) => setTimeout(resolve, 30));

    expect(researchStreamApi.start).not.toHaveBeenCalled();
    expect(wsInstances.length).toBe(0);
    expect(result.current.status).toBe("idle");
  });
});
