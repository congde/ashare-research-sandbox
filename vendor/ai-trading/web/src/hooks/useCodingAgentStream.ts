/**
 * React hook for streaming a coding-agent run over WebSocket.
 *
 * RFC 0002 §3.3.12.5 / TIER 3D. Owns a single WS connection per
 * session_id, parses v1 envelopes, exposes the running list of items
 * + current seq cursor + connection status. Auto-reconnects with the
 * cursor on transient close so the user never sees gaps.
 *
 * Does NOT render — pair with a presentation component that maps
 * envelope.kind to the right card UI.
 */

import { useEffect, useReducer, useRef } from "react";

import { authStorage } from "../utils/auth-storage";

export type StreamStatus = "connecting" | "open" | "closed" | "error";


export interface CodingAgentStreamItem {
  schema: string;
  session_id: string;
  seq: number;
  turn_seq: number;
  kind: string;
  payload: Record<string, unknown>;
  ts: string;
}


export interface UseCodingAgentStreamOptions {
  initialAfterSeq?: number;
  /** Auto-reconnect after a transient close (default true). */
  autoReconnect?: boolean;
  /** Delay between reconnect attempts in ms (default 1500). */
  reconnectDelayMs?: number;
}


export interface CodingAgentStreamResult {
  items: CodingAgentStreamItem[];
  cursor: number;
  status: StreamStatus;
}


// ── Reducer ─────────────────────────────────────────────────────


type State = {
  items: CodingAgentStreamItem[];
  cursor: number;
  status: StreamStatus;
};


type Action =
  | { type: "STATUS"; status: StreamStatus }
  | { type: "ITEM"; item: CodingAgentStreamItem }
  | { type: "RESET_FOR_RECONNECT" };


function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "STATUS":
      return { ...state, status: action.status };
    case "ITEM": {
      // Defensive: skip duplicates if a reconnect re-delivers an
      // item the server already sent (after_seq filter on the
      // backend should prevent this, but client-side dedupe makes
      // the contract robust to off-by-one bugs).
      if (action.item.seq <= state.cursor) {
        return state;
      }
      return {
        ...state,
        items: [...state.items, action.item],
        cursor: action.item.seq,
      };
    }
    case "RESET_FOR_RECONNECT":
      return { ...state, status: "connecting" };
    default:
      return state;
  }
}


// ── Helpers ─────────────────────────────────────────────────────


function buildUrl(sessionId: string, afterSeq: number): string {
  // Use authStorage abstraction so this hook keeps working when the
  // token migration runs (which deletes the localStorage key in favour
  // of sessionStorage). HIGH finding from WorkDAO MVP review.
  const token = authStorage.getToken() ?? "";
  // In dev, vite proxies /ws to ws://backend; in prod, same-origin.
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = window.location.host;
  const params = new URLSearchParams({
    token,
    after_seq: String(afterSeq),
  });
  return `${proto}//${host}/ws/coding-agent/${sessionId}?${params.toString()}`;
}


/** Codes that mean "don't bother reconnecting" — server-side
 * rejection (auth fail, not found) is permanent until the client
 * provides new credentials / a different session_id. */
const _PERMANENT_CLOSE_CODES = new Set([
  4001, // _WS_REJECTED (auth fail / cross-tenant)
  4500, // _WS_INTERNAL (server error — unlikely to fix itself)
]);


function parseEnvelope(raw: string): CodingAgentStreamItem | null {
  try {
    const data = JSON.parse(raw);
    if (typeof data !== "object" || data === null) return null;
    if (data.schema !== "v1") return null;
    if (typeof data.seq !== "number") return null;
    if (typeof data.kind !== "string") return null;
    return data as CodingAgentStreamItem;
  } catch {
    return null;
  }
}


// ── Hook ────────────────────────────────────────────────────────


export function useCodingAgentStream(
  sessionId: string,
  options: UseCodingAgentStreamOptions = {},
): CodingAgentStreamResult {
  const {
    initialAfterSeq = 0,
    autoReconnect = true,
    reconnectDelayMs = 1500,
  } = options;

  const [state, dispatch] = useReducer(reducer, {
    items: [],
    cursor: initialAfterSeq,
    status: "connecting",
  });

  // Refs so the WS callbacks always see the latest cursor / config
  // without re-running the connect effect on every state change.
  // The ref.current = ... pattern below intentionally writes during
  // render — it's a known idiom for keeping refs synced with prop
  // values in callback-heavy hooks. The React lint rule
  // ``react-hooks/refs`` flags this generically; we accept it
  // because the writes are pure (no side effect / no setState) and
  // the alternative (useEffect) would race against the WS
  // ``onmessage`` callback that consumes ``cursorRef.current``.
  const cursorRef = useRef(initialAfterSeq);
  // eslint-disable-next-line react-hooks/refs
  cursorRef.current = state.cursor;
  const sessionIdRef = useRef(sessionId);
  // eslint-disable-next-line react-hooks/refs
  sessionIdRef.current = sessionId;
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const intentionalCloseRef = useRef(false);

  useEffect(() => {
    intentionalCloseRef.current = false;

    function connect() {
      const ws = new WebSocket(buildUrl(sessionIdRef.current, cursorRef.current));
      wsRef.current = ws;
      ws.onopen = () => dispatch({ type: "STATUS", status: "open" });
      ws.onmessage = (ev) => {
        const env = parseEnvelope(typeof ev.data === "string" ? ev.data : "");
        if (env !== null) {
          dispatch({ type: "ITEM", item: env });
        }
      };
      ws.onerror = () => dispatch({ type: "STATUS", status: "error" });
      ws.onclose = (ev) => {
        wsRef.current = null;
        // Permanent close (auth fail / not found) → surface as error
        // so the UI can prompt the user to re-login or pick a
        // different session. Don't try to reconnect.
        if (_PERMANENT_CLOSE_CODES.has(ev.code)) {
          dispatch({ type: "STATUS", status: "error" });
          return;
        }
        if (intentionalCloseRef.current) {
          dispatch({ type: "STATUS", status: "closed" });
          return;
        }
        if (autoReconnect) {
          dispatch({ type: "RESET_FOR_RECONNECT" });
          reconnectTimerRef.current = setTimeout(connect, reconnectDelayMs);
        } else {
          dispatch({ type: "STATUS", status: "closed" });
        }
      };
    }

    connect();

    return () => {
      intentionalCloseRef.current = true;
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (wsRef.current !== null) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
     
  }, [sessionId, autoReconnect, reconnectDelayMs]);

  return {
    items: state.items,
    cursor: state.cursor,
    status: state.status,
  };
}
