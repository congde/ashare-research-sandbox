/**
 * ResearchStreamPanel — live ValueScan Stream subscribers.
 *
 * Mounts the `useResearchStream` hook to subscribe to the
 * `research-stream:market` room (or another channel chosen via
 * Segmented), then renders incoming events as a live log.
 *
 * This page is meant for operators to verify the upstream Stream
 * is delivering. For strategy / risk consumption, the same hook
 * can be embedded into the existing `/live` and `/risk` panels.
 */

import { useState } from "react";
import type { JSX } from "react";
import { Alert, Button, Segmented, Tag } from "antd";

import {
  EditorialHeading,
  QuantGlowCard,
} from "../../quant-atelier";
import { useResearchStream } from "../../hooks/useResearchStream";
import { TradingPageShell } from "../trading/TradingPageShell";
import "../trading/trading.css";

type ChannelKey = "market" | "signal";

const CHANNEL_OPTIONS: { label: string; value: ChannelKey; path: string }[] = [
  {
    label: "市场分析",
    value: "market",
    path: "/stream/market/subscribe",
  },
  {
    label: "代币信号",
    value: "signal",
    path: "/stream/signal/subscribe",
  },
];

const STATUS_TONE: Record<string, "blue" | "cyan" | "purple" | "green" | "red" | "orange" | "default"> = {
  idle: "default",
  starting: "blue",
  subscribing: "cyan",
  connected: "green",
  reconnecting: "orange",
  error: "red",
  stopped: "default",
};

const STATUS_LABEL: Record<string, string> = {
  idle: "未启动",
  starting: "请求订阅中...",
  subscribing: "正在订阅 room...",
  connected: "已连接",
  reconnecting: "重连中",
  error: "错误",
  stopped: "已停止",
};

/**
 * Try to JSON-parse the event payload for display; fall back to the
 * raw string when the upstream sends plain text (e.g. heartbeats).
 */
function formatEventData(raw: string): string {
  const trimmed = raw.trim();
  if (!trimmed) return "";
  try {
    return JSON.stringify(JSON.parse(trimmed), null, 2);
  } catch {
    return trimmed;
  }
}

function formatTimestamp(ms: number): string {
  const date = new Date(ms);
  return `${date.toLocaleTimeString()}.${date.getMilliseconds().toString().padStart(3, "0")}`;
}

export default function ResearchStreamPanel(): JSX.Element {
  const [channelKey, setChannelKey] = useState<ChannelKey>("market");

  const channel = CHANNEL_OPTIONS.find((c) => c.value === channelKey);
  const { status, events, error, metrics, roomName, clear } =
    useResearchStream({
      channel: channel?.path,
      maxEvents: 200,
      enabled: channel !== undefined,
    });

  return (
    <TradingPageShell
      eyebrow="Research Stream"
      title="实时市场情报"
      description="ValueScan SSE 推送 → 后端 ResearchStreamFanout → /ws WebSocket → 此面板。运营手动验证 Stream 实际能否拉到数据用。"
      actions={
        <Segmented
          value={channelKey}
          onChange={(v) => setChannelKey(v as ChannelKey)}
          options={CHANNEL_OPTIONS.map((c) => ({ label: c.label, value: c.value }))}
        />
      }
      aside={
        <QuantGlowCard
          variant={status === "connected" ? "live" : "default"}
        >
          <div className="trading-list">
            <div>
              <div className="trading-eyebrow" style={{ marginBottom: 6 }}>
                状态
              </div>
              <Tag
                color={STATUS_TONE[status] ?? "default"}
                style={{ fontFamily: "var(--qa-font-mono)" }}
              >
                {STATUS_LABEL[status] ?? status}
              </Tag>
            </div>
            <div>
              <div className="trading-eyebrow" style={{ marginBottom: 6 }}>
                Room
              </div>
              <div className="mono" style={{ fontSize: 13 }}>
                {roomName ?? "—"}
              </div>
            </div>
            <div>
              <div className="trading-eyebrow" style={{ marginBottom: 6 }}>
                收到事件
              </div>
              <div
                className="mono"
                data-testid="research-stream-event-count"
                style={{
                  fontSize: 22,
                  color: "var(--qa-text-1)",
                  fontWeight: 600,
                }}
              >
                {events.length}
              </div>
            </div>
            {metrics ? (
              <div>
                <div className="trading-eyebrow" style={{ marginBottom: 6 }}>
                  后端指标
                </div>
                <div
                  className="mono"
                  style={{ fontSize: 12, color: "var(--qa-text-2)" }}
                >
                  recv: {metrics.events_received} · sent: {metrics.events_published}
                  <br />
                  reconnects: {metrics.reconnects}
                </div>
              </div>
            ) : null}
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          {error ? (
            <Alert
              type="error"
              showIcon
              message="Stream 启动失败"
              description={error}
              style={{ marginBottom: 16 }}
            />
          ) : null}

          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              marginBottom: 12,
            }}
          >
            <EditorialHeading level={3} rule={false}>
              事件流(最近 {events.length})
            </EditorialHeading>
            <Button
              size="small"
              onClick={clear}
              disabled={events.length === 0}
              data-testid="research-stream-clear"
            >
              清空缓冲
            </Button>
          </div>

          {events.length === 0 && status === "connected" ? (
            <div
              style={{
                padding: 40,
                textAlign: "center",
                color: "var(--qa-text-3)",
              }}
            >
              已连接,等待 ValueScan 推送事件...
              <br />
              <span style={{ fontSize: 11 }}>
                (此通道可能需要特定 query_params 才会推流;参考 docs/integrations/valuescan-dexscan.md)
              </span>
            </div>
          ) : null}

          <div
            data-testid="research-stream-event-log"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: 8,
              maxHeight: 600,
              overflowY: "auto",
            }}
          >
            {[...events].reverse().map((event, idx) => (
              <div
                key={`${event.receivedAt}-${idx}`}
                style={{
                  padding: 12,
                  border: "1px solid var(--qa-line-faint, #182142)",
                  borderRadius: 6,
                  background: "rgba(10, 15, 27, 0.5)",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    gap: 12,
                    marginBottom: 6,
                    alignItems: "center",
                  }}
                >
                  <span
                    className="mono"
                    style={{
                      fontSize: 11,
                      color: "var(--qa-neutral, #00d4ff)",
                      padding: "2px 6px",
                      border: "1px solid var(--qa-neutral, #00d4ff)",
                      borderRadius: 3,
                      letterSpacing: "0.04em",
                    }}
                  >
                    {event.event}
                  </span>
                  <span
                    className="mono"
                    style={{
                      fontSize: 11,
                      color: "var(--qa-text-3)",
                    }}
                  >
                    {formatTimestamp(event.receivedAt)}
                  </span>
                </div>
                <pre
                  className="trading-console"
                  style={{
                    margin: 0,
                    fontSize: 12,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {formatEventData(event.data)}
                </pre>
              </div>
            ))}
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
