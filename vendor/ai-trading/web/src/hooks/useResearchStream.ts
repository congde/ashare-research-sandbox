/**
 * useResearchStream — subscribe to a ValueScan research-stream room.
 *
 * Lifecycle (on mount):
 *   1. POST /research/stream/start to register the upstream subscription
 *   2. Open a WebSocket to /ws
 *   3. Send {"action":"subscribe", "room": <room>} to join the room
 *   4. Push every incoming `research_stream` message into the events buffer
 *
 * Lifecycle (on unmount):
 *   1. Send {"action":"unsubscribe", "room": <room>}
 *   2. Close the WebSocket
 *   3. POST /research/stream/stop to release the upstream subscription
 *      (NOTE: the fanout uses per-room idempotency; if another user
 *       hook is still subscribed to the same room, the upstream
 *       subscription stays open. The stop is best-effort cleanup.)
 *
 * The hook is BUFFERED — callers see all events that arrived during
 * the component's lifetime, capped by `maxEvents` (oldest dropped).
 * For a "scroll-back forever" panel, point this at a state store
 * (Zustand / Redux) instead of relying on the in-hook buffer.
 *
 * Reconnect on WebSocket drops:
 * - WebSocket drops happen routinely on long-running sessions
 * - The hook reconnects with the same 1s→30s exponential backoff
 *   that the backend uses, so frontend + backend logging matches
 * - The buffer is preserved across reconnects so the UI doesn't
 *   flash empty during a blip
 */

import { useEffect, useRef, useState } from "react";

import {
  researchStreamApi,
  type ResearchStreamMetrics,
} from "../api/services";
import { authStorage } from "../utils/auth-storage";

const RECONNECT_INITIAL_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;
const RECONNECT_MULTIPLIER = 2;

/**
 * One event delivered through the research-stream room.
 *
 * `event` is the raw SSE event name from upstream (e.g.
 * "market_analysis", "opportunity"). `data` is the raw string —
 * usually JSON, but the hook doesn't parse it (the caller's
 * channel-specific code does, since the schema varies per event
 * type).
 */
export interface ResearchStreamMessage {
  event: string;
  data: string;
  receivedAt: number;
  retry: number | null;
}

export type ResearchStreamStatus =
  | "idle"
  | "starting"
  | "subscribing"
  | "connected"
  | "reconnecting"
  | "error"
  | "stopped";

interface UseResearchStreamOptions {
  /**
   * Channel path to subscribe to. Defaults to ValueScan market
   * commentary.
   */
  channel?: string;
  /** Per-channel filter params forwarded to the upstream SSE call. */
  queryParams?: Record<string, unknown>;
  /** Max events kept in the buffer. Default 200. */
  maxEvents?: number;
  /** Set to false to disable the subscription. Useful for tabs. */
  enabled?: boolean;
}

interface UseResearchStreamResult {
  status: ResearchStreamStatus;
  events: ResearchStreamMessage[];
  error: string | null;
  metrics: ResearchStreamMetrics | null;
  roomName: string | null;
  /** Clear the buffer without closing the connection. */
  clear: () => void;
}

/**
 * Subscribe to a `research-stream:*` room.
 *
 * Returns reactive `events` array + `status`. Caller renders;
 * cleanup is automatic on unmount.
 */
export function useResearchStream(
  options: UseResearchStreamOptions = {},
): UseResearchStreamResult {
  const {
    channel = "/stream/market/subscribe",
    queryParams,
    maxEvents = 200,
    enabled = true,
  } = options;

  const [status, setStatus] = useState<ResearchStreamStatus>("idle");
  const [events, setEvents] = useState<ResearchStreamMessage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<ResearchStreamMetrics | null>(null);
  const [roomName, setRoomName] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectDelayRef = useRef(RECONNECT_INITIAL_MS);
  const cancelledRef = useRef(false);
  const roomNameRef = useRef<string | null>(null);

  const clear = (): void => setEvents([]);

  useEffect(() => {
    // Disabled — make sure nothing's running.
    if (!enabled) {
      setStatus("idle");
      return;
    }

    cancelledRef.current = false;
    let cancelled = false;

    const pushEvent = (msg: ResearchStreamMessage): void => {
      setEvents((prev) => {
        const next = [...prev, msg];
        if (next.length > maxEvents) {
          // Drop oldest — keep the buffer bounded.
          next.splice(0, next.length - maxEvents);
        }
        return next;
      });
    };

    const connectWebSocket = (room: string): void => {
      if (cancelled) return;

      const token = authStorage.getToken() ?? undefined;
      const wsBase = import.meta.env.VITE_WS_BASE ?? "ws://localhost:8000";
      const url = token ? `${wsBase}/ws?token=${token}` : `${wsBase}/ws`;
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.addEventListener("open", () => {
        if (cancelled) {
          ws.close();
          return;
        }
        setStatus("subscribing");
        ws.send(JSON.stringify({ action: "subscribe", room }));
      });

      ws.addEventListener("message", (msgEvent: MessageEvent<string>) => {
        if (cancelled) return;
        let payload: unknown;
        try {
          payload = JSON.parse(msgEvent.data);
        } catch {
          // Non-JSON frames — the /ws router always sends JSON, so
          // this shouldn't happen. Log to console and skip.
          // eslint-disable-next-line no-console
          console.warn("research-stream: non-JSON ws frame", msgEvent.data);
          return;
        }
        if (typeof payload !== "object" || payload === null) return;

        const obj = payload as Record<string, unknown>;
        if (obj.action === "subscribed") {
          setStatus("connected");
          setError(null);
          reconnectDelayRef.current = RECONNECT_INITIAL_MS;
          return;
        }
        if (obj.type === "research_stream") {
          const innerPayload = obj.payload as Record<string, unknown> | undefined;
          if (innerPayload) {
            pushEvent({
              event: String(innerPayload.event ?? "message"),
              data: String(innerPayload.data ?? ""),
              receivedAt: Date.now(),
              retry:
                typeof innerPayload.retry === "number"
                  ? innerPayload.retry
                  : null,
            });
          }
        }
      });

      ws.addEventListener("error", () => {
        if (cancelled) return;
        setStatus("error");
        setError("WebSocket transport error");
      });

      ws.addEventListener("close", () => {
        if (cancelled) return;
        // Reconnect with backoff (mirrors the backend's policy).
        setStatus("reconnecting");
        const delay = reconnectDelayRef.current;
        reconnectDelayRef.current = Math.min(
          delay * RECONNECT_MULTIPLIER,
          RECONNECT_MAX_MS,
        );
        reconnectTimeoutRef.current = setTimeout(() => {
          if (!cancelled) connectWebSocket(room);
        }, delay);
      });
    };

    const run = async (): Promise<void> => {
      setStatus("starting");
      setError(null);
      try {
        const startRes = await researchStreamApi.start({
          channel,
          query_params: queryParams ?? null,
        });
        if (cancelled) return;
        const room = startRes.data.room_name;
        roomNameRef.current = room;
        setRoomName(room);
        setMetrics(startRes.data.metrics);
        connectWebSocket(room);
      } catch (err: unknown) {
        if (cancelled) return;
        const detail =
          (err as { response?: { data?: { detail?: string } } }).response?.data
            ?.detail ?? (err instanceof Error ? err.message : "Unknown");
        setStatus("error");
        setError(`Failed to start stream: ${detail}`);
      }
    };

    void run();

    return () => {
      cancelled = true;
      cancelledRef.current = true;
      if (reconnectTimeoutRef.current !== null) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      const ws = wsRef.current;
      const room = roomNameRef.current;
      if (ws !== null && room !== null) {
        // Best-effort unsubscribe before close.
        try {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ action: "unsubscribe", room }));
          }
        } catch {
          // Ignore — closing immediately anyway.
        }
        ws.close();
      }
      wsRef.current = null;

      // Best-effort backend cleanup. The fanout's per-room
      // idempotency means this only really stops if we're the
      // last subscriber.
      if (room !== null) {
        researchStreamApi
          .stop({ room_name: room })
          .catch(() => {
            // Tab might already be navigated away — silent.
          });
      }
      setStatus("stopped");
    };
  }, [channel, JSON.stringify(queryParams ?? null), enabled, maxEvents]);

  return { status, events, error, metrics, roomName, clear };
}
