/**
 * useCoordinationLive — RFC 0007 Slice D8
 *
 * Subscribes to the WebSocket gateway's per-run coordination room
 * (``coord_run:<run_id>``) and invokes ``onEvent`` whenever the
 * server pushes a coordination event whose ``event_type`` matches
 * one in the caller-supplied filter list.
 *
 * Why a shared hook
 * -----------------
 * D6/D7/D9 ship five publishers (spawn / inbox / scratchpad / bus /
 * deadlock) that all emit into the same coord_run room with the
 * same envelope shape. Every admin viewer
 * (TraceTree / InboxPanel / Scratchpad / BusTopics) needs the same
 * connect → subscribe → filter → refetch pattern. Putting it in one
 * hook means each page is just a few lines of glue plus its own
 * fetch function — no per-page WS lifecycle code to maintain.
 *
 * Throttle
 * --------
 * A burst of spawn events under load would otherwise hammer the
 * GET endpoint. We throttle ``onEvent`` calls so callers (typically
 * a refetch) fire at most once per ``throttleMs``. If multiple
 * events arrive inside the window the last one is delivered after
 * the window expires (trailing-edge), so the page always converges
 * on the latest state.
 *
 * Reconnect
 * ---------
 * On unexpected close (anything other than ``code === 1000``) the
 * hook reconnects with capped exponential backoff (1s / 2s / 4s /
 * 8s, max 8s) and re-subscribes. This matches the existing pattern
 * in TaskDetail.tsx.
 *
 * Disable / re-enable
 * -------------------
 * - Empty/undefined ``runId`` → no connection (caller hasn't entered
 *   a run id yet).
 * - ``enabled === false`` → tear down the connection (e.g. when the
 *   tab goes to background, or a higher-level switch is off).
 *
 * Lifecycle
 * ---------
 * The hook owns one WebSocket per (runId, enabled) tuple. Changing
 * either tears down the old socket and opens a new one. Unmount
 * cleans up cleanly with ``code === 1000`` so the server doesn't
 * see a spurious "connection lost".
 */

import { useEffect, useRef, useState } from "react";
import { authStorage } from "../utils/auth-storage";

export interface CoordinationEvent {
  event_type: string;
  payload: Record<string, unknown>;
  timestamp?: string;
}

export interface UseCoordinationLiveOptions {
  /** Run id to subscribe to. Empty / null / undefined → no connection. */
  runId: string | null | undefined;
  /**
   * Coordination event types to react to (e.g.
   * ``["coord.spawn.added"]``). Other events on the same room are
   * silently ignored. An empty list means "react to every
   * coordination_event" — useful for debug / catch-all viewers.
   */
  eventTypes: readonly string[];
  /** Called once per matching event (post-throttle). */
  onEvent: (event: CoordinationEvent) => void;
  /**
   * Minimum ms between successive ``onEvent`` calls. Bursts collapse
   * into one trailing-edge call. Default 500.
   */
  throttleMs?: number;
  /** When false, the hook tears down its connection. Default true. */
  enabled?: boolean;
}

export interface UseCoordinationLiveResult {
  /** True while the underlying WebSocket is OPEN and subscribed. */
  connected: boolean;
  /** The most recent matching event, or null if none yet. */
  lastEvent: CoordinationEvent | null;
}

const RECONNECT_DELAYS_MS = [1_000, 2_000, 4_000, 8_000];
const NORMAL_CLOSE_CODE = 1000;

function getWsUrl(): string {
  const wsBase = import.meta.env.VITE_WS_BASE;
  if (wsBase) return wsBase;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.hostname}:8000`;
}

function makeRoom(runId: string): string {
  return `coord_run:${runId}`;
}

export function useCoordinationLive(
  options: UseCoordinationLiveOptions,
): UseCoordinationLiveResult {
  const {
    runId,
    eventTypes,
    onEvent,
    throttleMs = 500,
    enabled = true,
  } = options;

  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState<CoordinationEvent | null>(null);

  // Refs let the effect read the latest values without restarting on every
  // render. Without these, recreating onEvent / eventTypes on every render
  // would tear down and reopen the WS, which is exactly what we want to
  // avoid.
  const onEventRef = useRef(onEvent);
  const eventTypesRef = useRef<readonly string[]>(eventTypes);
  const throttleMsRef = useRef(throttleMs);

  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);
  useEffect(() => {
    eventTypesRef.current = eventTypes;
  }, [eventTypes]);
  useEffect(() => {
    throttleMsRef.current = throttleMs;
  }, [throttleMs]);

  useEffect(() => {
    if (!runId || !enabled) {
      // RFC 0011 Phase F: previously this branch had to
      // ``setConnected(false)`` to clear the flag when transitioning
      // to disabled. We now rely on the ``ws.onclose`` handler from
      // the previous effect run (which fired during cleanup below)
      // to have already cleared the flag — the ``destroyed`` guard
      // there ensures the close handler still runs even though the
      // effect is unmounting. No setState-in-effect needed.
      return;
    }

    let ws: WebSocket | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let throttleTimer: ReturnType<typeof setTimeout> | null = null;
    let pendingEvent: CoordinationEvent | null = null;
    let lastFiredAt = 0;
    let attempt = 0;
    let destroyed = false;

    function fireThrottled(evt: CoordinationEvent) {
      const now = Date.now();
      const minGap = throttleMsRef.current;
      const elapsed = now - lastFiredAt;

      // Always remember the most recent event so the throttled handler can
      // pick the latest payload at fire time.
      pendingEvent = evt;
      setLastEvent(evt);

      if (elapsed >= minGap) {
        lastFiredAt = now;
        const toDeliver = pendingEvent;
        pendingEvent = null;
        onEventRef.current(toDeliver);
      } else if (throttleTimer == null) {
        const delay = minGap - elapsed;
        throttleTimer = setTimeout(() => {
          throttleTimer = null;
          if (pendingEvent && !destroyed) {
            lastFiredAt = Date.now();
            const toDeliver = pendingEvent;
            pendingEvent = null;
            onEventRef.current(toDeliver);
          }
        }, delay);
      }
    }

    function connect() {
      if (destroyed) return;
      const token = authStorage.getToken() ?? "";
      const url = `${getWsUrl()}/ws?token=${encodeURIComponent(token)}`;
      ws = new WebSocket(url);

      ws.onopen = () => {
        if (destroyed || ws == null) return;
        attempt = 0;
        setConnected(true);
        ws.send(
          JSON.stringify({ action: "subscribe", room: makeRoom(runId!) }),
        );
      };

      ws.onmessage = (e: MessageEvent<string>) => {
        if (destroyed) return;
        let msg: unknown;
        try {
          msg = JSON.parse(e.data);
        } catch {
          return;
        }
        if (
          typeof msg !== "object" ||
          msg == null ||
          (msg as { type?: unknown }).type !== "coordination_event"
        ) {
          return;
        }
        const typed = msg as {
          event_type?: string;
          payload?: Record<string, unknown>;
          timestamp?: string;
        };
        if (typeof typed.event_type !== "string") return;

        const allowed =
          eventTypesRef.current.length === 0 ||
          eventTypesRef.current.includes(typed.event_type);
        if (!allowed) return;

        fireThrottled({
          event_type: typed.event_type,
          payload: typed.payload ?? {},
          timestamp: typed.timestamp,
        });
      };

      ws.onerror = () => {
        // Browsers fire 'error' before 'close' on transport problems. We
        // act on 'close' so the reconnect logic only runs in one place.
      };

      ws.onclose = (ev: CloseEvent) => {
        setConnected(false);
        if (destroyed) return;
        if (ev.code === NORMAL_CLOSE_CODE) return;
        const delay =
          RECONNECT_DELAYS_MS[
            Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)
          ];
        attempt += 1;
        reconnectTimer = setTimeout(connect, delay);
      };
    }

    connect();

    return () => {
      destroyed = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (throttleTimer) clearTimeout(throttleTimer);
      if (ws != null) {
        try {
          // 1000 = normal close; tells the server this isn't a transport
          // error and to skip its own reconnect-friendly logging.
          ws.close(NORMAL_CLOSE_CODE);
        } catch {
          // swallow — we're tearing down anyway
        }
      }
      setConnected(false);
    };
    // eventTypes / onEvent / throttleMs deliberately omitted — they're
    // tracked via refs so the WS doesn't reconnect on every parent render.
  }, [runId, enabled]);

  return { connected, lastEvent };
}
