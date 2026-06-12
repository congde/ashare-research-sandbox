/**
 * Unit tests for useCoordinationLive (RFC 0007 Slice D8).
 *
 * The hook owns one WebSocket per (runId, enabled) tuple. On open
 * it subscribes to ``coord_run:<runId>``. Inbound messages with
 * ``type === "coordination_event"`` whose ``event_type`` matches
 * the caller's filter list invoke ``onEvent`` (throttled). The
 * hook reconnects with capped exponential backoff on unexpected
 * close and tears down cleanly on unmount.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type Mock,
} from "vitest";

import {
  useCoordinationLive,
  type CoordinationEvent,
} from "../../hooks/useCoordinationLive";

// ── In-memory WebSocket double ──────────────────────────────────


class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  readyState: number = 0; // CONNECTING
  onopen: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  // Track everything the hook .send()s us so we can assert on the
  // subscribe frame.
  sent: string[] = [];
  closed = false;
  closeCode?: number;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  // ── simulator helpers (called by tests) ──
  open() {
    this.readyState = 1; // OPEN
    this.onopen?.(new Event("open"));
  }

  emit(message: object) {
    this.onmessage?.(
      new MessageEvent("message", { data: JSON.stringify(message) }),
    );
  }

  emitRaw(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  remoteClose(code: number) {
    this.readyState = 3;
    this.closeCode = code;
    this.onclose?.(new CloseEvent("close", { code }));
  }

  close(code = 1000) {
    this.closed = true;
    this.readyState = 3;
    this.closeCode = code;
  }
}


// ── Test setup / teardown ───────────────────────────────────────


beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.spyOn(Storage.prototype, "getItem").mockImplementation((key) =>
    key === "de_token" ? "test-token" : null,
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});


function lastInstance(): FakeWebSocket {
  const instances = FakeWebSocket.instances;
  expect(instances.length).toBeGreaterThan(0);
  return instances[instances.length - 1]!;
}


// ── No-op behaviour ─────────────────────────────────────────────


describe("useCoordinationLive — no-op cases", () => {
  it("does not connect when runId is empty", () => {
    renderHook(() =>
      useCoordinationLive({
        runId: "",
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
      }),
    );
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("does not connect when runId is null", () => {
    renderHook(() =>
      useCoordinationLive({
        runId: null,
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
      }),
    );
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("does not connect when enabled=false even with valid runId", () => {
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
        enabled: false,
      }),
    );
    expect(FakeWebSocket.instances).toHaveLength(0);
  });
});


// ── Subscribe ───────────────────────────────────────────────────


describe("useCoordinationLive — subscribe", () => {
  it("opens a WS to /ws?token=…", () => {
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
      }),
    );
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(lastInstance().url).toContain("/ws?token=test-token");
  });

  it("sends a subscribe frame for coord_run:<runId> on open", () => {
    const { result } = renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
      }),
    );
    expect(result.current.connected).toBe(false);
    act(() => lastInstance().open());
    expect(result.current.connected).toBe(true);
    const frames = lastInstance().sent.map((s) => JSON.parse(s));
    expect(frames).toEqual([
      { action: "subscribe", room: "coord_run:r-1" },
    ]);
  });
});


// ── Filtering ───────────────────────────────────────────────────


describe("useCoordinationLive — filtering", () => {
  it("invokes onEvent only for matching event types", () => {
    const onEvent: Mock = vi.fn();
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent,
      }),
    );
    act(() => lastInstance().open());

    // Match — should fire
    act(() =>
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.spawn.added",
        payload: { child_run_id: "c-1" },
      }),
    );
    expect(onEvent).toHaveBeenCalledTimes(1);
    expect((onEvent.mock.calls[0]![0] as CoordinationEvent).payload).toEqual({
      child_run_id: "c-1",
    });

    // No match — should NOT fire
    act(() =>
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.scratchpad.set",
        payload: { field: "x" },
      }),
    );
    expect(onEvent).toHaveBeenCalledTimes(1);
  });

  it("with empty eventTypes, fires for every coordination_event", async () => {
    vi.useFakeTimers();
    const onEvent: Mock = vi.fn();
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: [],
        onEvent,
        // Default throttle would coalesce these two events; use a
        // tiny window so we can advance past it explicitly.
        throttleMs: 50,
      }),
    );
    act(() => lastInstance().open());

    act(() =>
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.spawn.added",
        payload: {},
      }),
    );
    // First event fires synchronously; second is throttled until the
    // window expires.
    expect(onEvent).toHaveBeenCalledTimes(1);
    act(() =>
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.scratchpad.set",
        payload: {},
      }),
    );
    await act(async () => {
      vi.advanceTimersByTime(80);
    });
    expect(onEvent).toHaveBeenCalledTimes(2);
  });

  it("ignores non-coordination_event messages", () => {
    const onEvent: Mock = vi.fn();
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent,
      }),
    );
    act(() => lastInstance().open());

    act(() =>
      lastInstance().emit({
        type: "task_event",
        event_type: "coord.spawn.added",
        payload: {},
      }),
    );
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("ignores malformed JSON without crashing", () => {
    const onEvent: Mock = vi.fn();
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent,
      }),
    );
    act(() => lastInstance().open());

    expect(() =>
      act(() => lastInstance().emitRaw("not json")),
    ).not.toThrow();
    expect(onEvent).not.toHaveBeenCalled();
  });
});


// ── Throttle ────────────────────────────────────────────────────


describe("useCoordinationLive — throttle", () => {
  it("collapses bursts into a trailing-edge call", async () => {
    vi.useFakeTimers();
    const onEvent: Mock = vi.fn();
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent,
        throttleMs: 200,
      }),
    );
    act(() => lastInstance().open());

    // First event fires immediately
    act(() =>
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.spawn.added",
        payload: { i: 1 },
      }),
    );
    expect(onEvent).toHaveBeenCalledTimes(1);

    // Three more inside the window — none fire yet
    act(() => {
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.spawn.added",
        payload: { i: 2 },
      });
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.spawn.added",
        payload: { i: 3 },
      });
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.spawn.added",
        payload: { i: 4 },
      });
    });
    expect(onEvent).toHaveBeenCalledTimes(1);

    // Advance past the throttle — exactly one trailing-edge call
    // with the LAST event fires.
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    expect(onEvent).toHaveBeenCalledTimes(2);
    expect((onEvent.mock.calls[1]![0] as CoordinationEvent).payload).toEqual({
      i: 4,
    });
  });
});


// ── Reconnect ───────────────────────────────────────────────────


describe("useCoordinationLive — reconnect", () => {
  it("does NOT reconnect after a normal close (code 1000)", () => {
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
      }),
    );
    act(() => lastInstance().open());
    act(() => lastInstance().remoteClose(1000));
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reconnects after a transient close (code 1006)", async () => {
    vi.useFakeTimers();
    renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
      }),
    );
    act(() => lastInstance().open());
    act(() => lastInstance().remoteClose(1006));
    // Backoff hasn't elapsed yet
    expect(FakeWebSocket.instances).toHaveLength(1);
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(FakeWebSocket.instances).toHaveLength(2);
    // Second connection re-subscribes once it opens
    act(() => lastInstance().open());
    const frames = lastInstance().sent.map((s) => JSON.parse(s));
    expect(frames).toContainEqual({
      action: "subscribe",
      room: "coord_run:r-1",
    });
  });
});


// ── Lifecycle ───────────────────────────────────────────────────


describe("useCoordinationLive — lifecycle", () => {
  it("closes the WS on unmount", () => {
    const { unmount } = renderHook(() =>
      useCoordinationLive({
        runId: "r-1",
        eventTypes: ["coord.spawn.added"],
        onEvent: vi.fn(),
      }),
    );
    act(() => lastInstance().open());
    const ws = lastInstance();
    unmount();
    expect(ws.closed).toBe(true);
    expect(ws.closeCode).toBe(1000);
  });

  it("changing runId tears down the old WS and opens a new one", async () => {
    const { rerender } = renderHook(
      ({ runId }: { runId: string }) =>
        useCoordinationLive({
          runId,
          eventTypes: ["coord.spawn.added"],
          onEvent: vi.fn(),
        }),
      { initialProps: { runId: "r-A" } },
    );
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0]!.url).toContain("token=test-token");
    const oldWs = FakeWebSocket.instances[0]!;
    act(() => oldWs.open());

    rerender({ runId: "r-B" });
    await waitFor(() => {
      expect(FakeWebSocket.instances).toHaveLength(2);
    });
    expect(oldWs.closed).toBe(true);
    act(() => FakeWebSocket.instances[1]!.open());
    const frames = FakeWebSocket.instances[1]!.sent.map((s) =>
      JSON.parse(s),
    );
    expect(frames).toContainEqual({
      action: "subscribe",
      room: "coord_run:r-B",
    });
  });

  it("does not reconnect WS when only the onEvent callback changes", async () => {
    const { rerender } = renderHook(
      ({ onEvent }: { onEvent: () => void }) =>
        useCoordinationLive({
          runId: "r-1",
          eventTypes: ["coord.spawn.added"],
          onEvent,
        }),
      { initialProps: { onEvent: vi.fn() } },
    );
    expect(FakeWebSocket.instances).toHaveLength(1);
    act(() => lastInstance().open());

    // Re-render with a brand-new function reference (the worry that
    // motivates the ref-based design)
    const newFn = vi.fn();
    rerender({ onEvent: newFn });

    // Crucially — STILL only one WS instance
    expect(FakeWebSocket.instances).toHaveLength(1);

    // And the new callback now receives events
    act(() =>
      lastInstance().emit({
        type: "coordination_event",
        event_type: "coord.spawn.added",
        payload: { x: 1 },
      }),
    );
    expect(newFn).toHaveBeenCalledTimes(1);
  });
});
