/**
 * ResearchPanel — single page over the 38 ValueScan + DexScan tools.
 *
 * Three regions:
 *   1. KPI strip — total tools + per-source configured indicator
 *   2. Catalogue grid — every tool as a clickable card, grouped by source
 *   3. Invocation console — JSON payload editor + result viewer for the
 *      currently selected tool
 *
 * Design notes:
 *   - All UI uses the Quant Atelier system already in code (no AntD
 *     Card; we use QuantGlowCard + raw markup for tighter control).
 *   - The payload editor accepts dict OR list JSON — some DexScan
 *     endpoints want array bodies. The textarea defaults to `{}` /
 *     `[{}]` based on the selected tool's source.
 *   - Invocation goes through `/api/v1/research/invoke` so the
 *     Strategy Architect (when wired) and the panel share one path.
 *   - Failed parses / 404 / 502 / 503 are surfaced inline with the
 *     same error envelope shape so the panel reads like a console
 *     not a form.
 */

import { useMemo, useState } from "react";
import type { JSX } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Input, Segmented, Tag, message } from "antd";

import {
  researchApi,
  type ResearchInvokeResponse,
  type ResearchSource,
  type ResearchToolInfo,
} from "../../api/services";
import { EditorialHeading, QuantGlowCard } from "../../quant-atelier";
import { TradingPageShell } from "../trading/TradingPageShell";
import "../trading/trading.css";

type SourceFilter = "all" | ResearchSource;

interface InvokeState {
  status: "idle" | "running" | "success" | "error";
  data: ResearchInvokeResponse | null;
  error: string | null;
  // Round-trip timing so the operator can see how fast each tool is.
  elapsedMs: number | null;
}

const SOURCE_LABEL: Record<ResearchSource, string> = {
  vs: "ValueScan · CEX",
  dex: "DexScan · DEX",
  mcp: "ValueScan · MCP",
};

/**
 * Pick a sensible default payload for a tool the user hasn't typed
 * for yet. Seed shape comes from the backend's body_shape hint;
 * known-working examples (chainName / tokenContractAddress for
 * DexScan, vsTokenId for ValueScan) are pre-filled so the user can
 * just click "调用" and see real data.
 *
 * This is just an editor seed — the user can overwrite anything.
 */
function defaultPayloadFor(tool: ResearchToolInfo): string {
  // DexScan — branch on the discovered body shape.
  if (tool.source === "dex") {
    // USDT on Ethereum — known-good probe target used during the
    // schema discovery work. Real users will edit to their token.
    const usdtSample = {
      chainName: "ETH",
      tokenContractAddress: "0xdac17f958d2ee523a2206206994597c13d831ec7",
    };

    switch (tool.body_shape) {
      case "coin_key":
        return JSON.stringify(usdtSample, null, 2);
      case "coin_key_list":
        return JSON.stringify([usdtSample], null, 2);
      case "unknown":
        // Hint payload — empty object plus a comment in the editor's
        // surrounding area would be ideal, but JSON has no comments,
        // so we pre-fill the chainName + address keys to give the
        // user a starting point. They'll add endpoint-specific fields
        // via raw_post probing if needed.
        return JSON.stringify({ ...usdtSample }, null, 2);
      default:
        return JSON.stringify({}, null, 2);
    }
  }

  // ValueScan — payload is always a dict; specific shape varies.
  if (tool.local_key === "tokens") {
    return JSON.stringify({ search: "BTC", pageSize: 5 }, null, 2);
  }
  if (
    [
      "token_detail",
      "kline",
      "realtime_funds",
      "funds_snapshot",
      "main_cost",
      "token_flow",
      "balance_trend",
      "profit_trend",
      "hold_cost_trend",
      "tx_count_trend",
      "holder_address",
    ].includes(tool.local_key)
  ) {
    return JSON.stringify({ vsTokenId: 1 }, null, 2);
  }
  return JSON.stringify({}, null, 2);
}

export default function ResearchPanel(): JSX.Element {
  // Catalogue — refetch on tab focus only; the surface is essentially
  // static within a session. 30s stale window matches the QueryClient
  // default in App.tsx so we stay consistent across the app.
  const catalogueQuery = useQuery({
    queryKey: ["research-catalogue"],
    queryFn: () => researchApi.catalogue().then((res) => res.data),
  });

  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [payloadText, setPayloadText] = useState<string>("{}");
  const [invokeState, setInvokeState] = useState<InvokeState>({
    status: "idle",
    data: null,
    error: null,
    elapsedMs: null,
  });

  const catalogue = catalogueQuery.data;
  const tools = catalogue?.tools ?? [];

  const visibleTools = useMemo(() => {
    const term = search.trim().toLowerCase();
    return tools.filter((tool) => {
      if (sourceFilter !== "all" && tool.source !== sourceFilter) {
        return false;
      }
      if (!term) return true;
      return (
        tool.qualified_key.toLowerCase().includes(term) ||
        tool.label.toLowerCase().includes(term) ||
        tool.local_key.toLowerCase().includes(term)
      );
    });
  }, [tools, sourceFilter, search]);

  const selectedTool = useMemo(
    () => tools.find((t) => t.qualified_key === selectedKey) ?? null,
    [tools, selectedKey],
  );

  const handleSelect = (tool: ResearchToolInfo): void => {
    setSelectedKey(tool.qualified_key);
    setPayloadText(defaultPayloadFor(tool));
    setInvokeState({
      status: "idle",
      data: null,
      error: null,
      elapsedMs: null,
    });
  };

  const handleInvoke = async (): Promise<void> => {
    if (!selectedTool) return;

    // Parse the payload editor — accept dict OR list. Surface parse
    // errors inline so the user can correct the JSON without losing
    // the tool selection.
    let parsedPayload: unknown;
    try {
      const trimmed = payloadText.trim();
      parsedPayload = trimmed === "" ? null : JSON.parse(trimmed);
    } catch (err: unknown) {
      const reason = err instanceof Error ? err.message : "invalid JSON";
      setInvokeState({
        status: "error",
        data: null,
        error: `Payload is not valid JSON: ${reason}`,
        elapsedMs: null,
      });
      return;
    }

    if (
      parsedPayload !== null
      && typeof parsedPayload !== "object"
    ) {
      setInvokeState({
        status: "error",
        data: null,
        error: "Payload must be a JSON object or array.",
        elapsedMs: null,
      });
      return;
    }

    setInvokeState({
      status: "running",
      data: null,
      error: null,
      elapsedMs: null,
    });

    const t0 = performance.now();
    try {
      const res = await researchApi.invoke({
        tool: selectedTool.qualified_key,
        payload: parsedPayload as Record<string, unknown> | unknown[],
      });
      const elapsed = Math.round(performance.now() - t0);
      setInvokeState({
        status: "success",
        data: res.data,
        error: null,
        elapsedMs: elapsed,
      });
      // A toast on success keeps the operator's attention on the result
      // pane (otherwise the change is below the fold for long payloads).
      message.success(`${selectedTool.qualified_key} · ${elapsed}ms`);
    } catch (err: unknown) {
      const elapsed = Math.round(performance.now() - t0);
      const status = (err as { response?: { status?: number } }).response?.status;
      const detail =
        (err as { response?: { data?: { detail?: string } } }).response?.data?.detail
        ?? (err instanceof Error ? err.message : "Unknown error");
      setInvokeState({
        status: "error",
        data: null,
        error: status ? `HTTP ${status}: ${detail}` : `${detail}`,
        elapsedMs: elapsed,
      });
    }
  };

  return (
    <TradingPageShell
      eyebrow="Research Agent"
      title="市场情报 · ValueScan + DexScan"
      description="38 个工具,一个 namespace。AI 写策略时调用的研究层入口,操作员手动查询也走这套接口。"
      aside={
        catalogue ? (
          <QuantGlowCard>
            <div className="trading-list">
              <div>
                <div className="trading-eyebrow" style={{ marginBottom: 6 }}>
                  Tools 总数
                </div>
                <div
                  className="mono"
                  data-testid="research-total-tools"
                  style={{
                    fontFamily: "var(--qa-font-mono)",
                    fontSize: 24,
                    fontWeight: 600,
                    color: "var(--qa-text-1)",
                  }}
                >
                  {catalogue.total}
                </div>
              </div>
              <div>
                <div className="trading-eyebrow" style={{ marginBottom: 6 }}>
                  ValueScan
                </div>
                <StatusBadge configured={catalogue.valuescan_configured} />
              </div>
              <div>
                <div className="trading-eyebrow" style={{ marginBottom: 6 }}>
                  DexScan
                </div>
                <StatusBadge configured={catalogue.dexscan_configured} />
              </div>
            </div>
          </QuantGlowCard>
        ) : null
      }
    >
      <section className="trading-grid">
        {/* ── Filters + search ─────────────────────────────────── */}
        <QuantGlowCard className="trading-span-12">
          <div
            style={{
              display: "flex",
              gap: 16,
              flexWrap: "wrap",
              alignItems: "center",
            }}
          >
            <Segmented
              value={sourceFilter}
              onChange={(v) => setSourceFilter(v as SourceFilter)}
              options={[
                { label: `全部 (${tools.length})`, value: "all" },
                {
                  label: `ValueScan (${tools.filter((t) => t.source === "vs").length})`,
                  value: "vs",
                },
                {
                  label: `DexScan (${tools.filter((t) => t.source === "dex").length})`,
                  value: "dex",
                },
              ]}
            />
            <Input.Search
              placeholder="搜工具名 / 描述 / 路径"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ flex: 1, minWidth: 240 }}
              allowClear
            />
            <div style={{ color: "var(--qa-text-3)", fontSize: 12 }}>
              当前 {visibleTools.length} / {tools.length} 个
            </div>
          </div>
        </QuantGlowCard>

        {/* ── Tool grid ────────────────────────────────────────── */}
        <QuantGlowCard className="trading-span-7">
          {catalogueQuery.isLoading ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--qa-text-3)" }}>
              加载工具目录…
            </div>
          ) : catalogueQuery.isError ? (
            <Alert
              type="error"
              showIcon
              message="无法加载 Research 目录"
              description="检查后端 /api/v1/research/catalogue 端点是否注册"
            />
          ) : (
            <div className="research-grid">
              {visibleTools.map((tool) => (
                <ToolCard
                  key={tool.qualified_key}
                  tool={tool}
                  selected={tool.qualified_key === selectedKey}
                  onClick={() => handleSelect(tool)}
                />
              ))}
              {visibleTools.length === 0 ? (
                <div
                  style={{
                    gridColumn: "1 / -1",
                    padding: 32,
                    textAlign: "center",
                    color: "var(--qa-text-3)",
                  }}
                >
                  没匹配的工具,换个关键词试试
                </div>
              ) : null}
            </div>
          )}
        </QuantGlowCard>

        {/* ── Invocation console ───────────────────────────────── */}
        <QuantGlowCard className="trading-span-5">
          {!selectedTool ? (
            <div
              style={{
                padding: 32,
                textAlign: "center",
                color: "var(--qa-text-3)",
              }}
            >
              <EditorialHeading level={3} rule={false}>
                选一个工具
              </EditorialHeading>
              <p style={{ marginTop: 12 }}>
                左边卡片任选,会自动填一个示例 payload。
              </p>
            </div>
          ) : (
            <>
              <div style={{ marginBottom: 12 }}>
                <Tag color={selectedTool.source === "vs" ? "blue" : "purple"}>
                  {SOURCE_LABEL[selectedTool.source]}
                </Tag>
                <div
                  className="mono"
                  style={{ fontSize: 18, marginTop: 8 }}
                >
                  {selectedTool.qualified_key}
                </div>
                <div
                  style={{
                    color: "var(--qa-text-3)",
                    fontSize: 12,
                    marginTop: 4,
                  }}
                >
                  {selectedTool.path}
                </div>
                <p
                  style={{
                    color: "var(--qa-text-2)",
                    fontSize: 13,
                    marginTop: 12,
                  }}
                >
                  {selectedTool.label}
                </p>
              </div>

              <div
                style={{
                  fontSize: 11,
                  color: "var(--qa-text-3)",
                  marginBottom: 6,
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                }}
              >
                Payload (JSON · dict 或 list)
              </div>
              <Input.TextArea
                value={payloadText}
                onChange={(e) => setPayloadText(e.target.value)}
                rows={8}
                style={{
                  fontFamily: "var(--qa-font-mono)",
                  fontSize: 13,
                }}
                placeholder='{"vsTokenId": 1}'
              />
              <div
                style={{
                  marginTop: 12,
                  display: "flex",
                  gap: 8,
                  justifyContent: "flex-end",
                }}
              >
                <Button
                  className="btn-gradient"
                  type="primary"
                  loading={invokeState.status === "running"}
                  onClick={handleInvoke}
                  data-testid="research-invoke"
                >
                  调用
                </Button>
              </div>

              {invokeState.error ? (
                <Alert
                  type="error"
                  showIcon
                  message="调用失败"
                  description={invokeState.error}
                  style={{ marginTop: 16 }}
                />
              ) : null}

              {invokeState.status === "success" && invokeState.data ? (
                <div style={{ marginTop: 16 }}>
                  <div
                    style={{
                      fontSize: 11,
                      color: "var(--qa-text-3)",
                      marginBottom: 6,
                      letterSpacing: "0.04em",
                      textTransform: "uppercase",
                      display: "flex",
                      justifyContent: "space-between",
                    }}
                  >
                    <span>Response</span>
                    <span>
                      {invokeState.elapsedMs !== null
                        ? `${invokeState.elapsedMs} ms`
                        : ""}
                    </span>
                  </div>
                  <pre
                    className="trading-console"
                    data-testid="research-response"
                    style={{ maxHeight: 360, overflow: "auto" }}
                  >
                    {JSON.stringify(invokeState.data.data, null, 2)}
                  </pre>
                </div>
              ) : null}
            </>
          )}
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}

function StatusBadge({ configured }: { configured: boolean }): JSX.Element {
  return (
    <Tag
      color={configured ? "green" : "default"}
      style={{ fontFamily: "var(--qa-font-mono)", margin: 0 }}
    >
      {configured ? "已配置" : "未配置"}
    </Tag>
  );
}

interface ToolCardProps {
  tool: ResearchToolInfo;
  selected: boolean;
  onClick: () => void;
}

// Compact body-shape badge: signals "this tool's payload schema has
// been verified" (coin_key / coin_key_list / dict) vs "still TBD".
const SHAPE_BADGE: Record<string, { label: string; tone: string }> = {
  dict: { label: "dict", tone: "rgba(0, 212, 255, 0.6)" },
  coin_key: { label: "coin_key", tone: "rgba(0, 255, 163, 0.7)" },
  coin_key_list: { label: "[coin_key]", tone: "rgba(0, 255, 163, 0.7)" },
  mcp: { label: "mcp", tone: "rgba(123, 91, 255, 0.7)" },
  unknown: { label: "schema TBD", tone: "rgba(255, 182, 39, 0.7)" },
};

function ToolCard({ tool, selected, onClick }: ToolCardProps): JSX.Element {
  const shape = SHAPE_BADGE[tool.body_shape] ?? SHAPE_BADGE.unknown;
  return (
    <button
      type="button"
      className={`research-tool ${selected ? "research-tool-selected" : ""}`}
      onClick={onClick}
      data-testid={`research-tool-${tool.qualified_key}`}
    >
      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 6,
          alignItems: "center",
        }}
      >
        <span
          className={`research-tool-source research-tool-source-${tool.source}`}
        >
          {tool.source.toUpperCase()}
        </span>
        <span
          className="mono"
          style={{ fontSize: 13, fontWeight: 600, color: "var(--qa-text-1)" }}
        >
          {tool.local_key}
        </span>
        <span
          className="mono"
          style={{
            marginLeft: "auto",
            fontSize: 9,
            color: shape.tone,
            padding: "1px 5px",
            borderRadius: 3,
            border: `1px solid ${shape.tone}`,
          }}
          title={`body_shape: ${tool.body_shape}`}
        >
          {shape.label}
        </span>
      </div>
      <div
        style={{
          fontSize: 12,
          color: "var(--qa-text-2)",
          lineHeight: 1.5,
        }}
      >
        {tool.label}
      </div>
    </button>
  );
}
