import { SaveOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { Alert, Button, Input, Segmented, Tag, message } from "antd";
import { useState } from "react";
import type { JSX } from "react";

import {
  type GenerateStrategyResponse,
  type StrategyGenerationFinding,
  strategiesApi,
} from "../../api/services";
import { AIAuroraInput } from "../../quant-atelier";
import {
  MetricTile,
  QuantGlowCard,
  ScoreRail,
  SectionHeader,
  SignalRow,
  StatusPill,
  TradingPageShell,
} from "./TradingPageShell";

const fixtureSketch = `# Submit a prompt above to generate real strategy code.
# Until you do, this pane shows a fixture sketch.

strategy:
  universe: BTC/USDT, ETH/USDT
  timeframe: 4h
  signal:
    trend: ema_20 > ema_60
    confirmation: valuescan.sentiment_zscore > 0.6
    volatility_filter: atr_pct between 1.2 and 4.5
  risk:
    max_position_pct: 18
    stop_loss_atr: 2.2
    cooldown_bars: 3`;

// Generation target — the strategy code itself is symbol-agnostic; these
// shape the prompt and are recorded on the saved strategy's card so the
// library can show provenance.
const GEN_SYMBOL = "BTC/USDT";
const GEN_TIMEFRAME = "1h";

/** Derive a default library name from the prompt (first ~40 chars). */
function defaultStrategyName(prompt: string): string {
  const trimmed = prompt.trim().replace(/\s+/g, " ");
  return trimmed.length > 40 ? `${trimmed.slice(0, 40)}…` : trimmed;
}

/**
 * Format an LLM-generation finding for display. The backend tags each
 * finding with a layer (validator vs lookahead) and a rule id — we
 * surface both so the user can map back to the SKILL.md rule table.
 */
function findingChip(finding: StrategyGenerationFinding): JSX.Element {
  const tone = finding.layer === "lookahead" ? "orange" : "red";
  return (
    <Tag color={tone} key={`${finding.rule}-${finding.line}-${finding.col}`}>
      L{finding.line} [{finding.rule}] {finding.message}
    </Tag>
  );
}

export default function StrategyCopilotPage() {
  const [prompt, setPrompt] = useState(
    "BTC 1h SMA-20/50 crossover strategy with 0.001 BTC qty per trade.",
  );
  const [mode, setMode] = useState<string | number>("策略生成");
  const [result, setResult] = useState<GenerateStrategyResponse | null>(null);
  const [saveName, setSaveName] = useState("");

  // useMutation gives us idle / pending / success / error states without
  // bespoke loading flags. On success we cache the response in component
  // state so the user can iterate on the prompt without losing the prior
  // result.
  const mutation = useMutation({
    mutationFn: () =>
      strategiesApi
        .generate({ prompt, symbol: GEN_SYMBOL, timeframe: GEN_TIMEFRAME })
        .then((res) => res.data),
    onSuccess: (data) => {
      setResult(data);
      if (data.success) {
        // Seed the library name — prefer the LLM card's name, else the prompt.
        setSaveName((prev) => prev || data.card?.name || defaultStrategyName(prompt));
        message.success("策略生成成功 — 请审阅代码");
      } else {
        message.warning(
          data.budget_exhausted
            ? "预算耗尽 — 请精简 prompt 或升级 tier"
            : "重试已耗尽 — 请细化 prompt 后重新生成",
        );
      }
    },
    onError: (err: unknown) => {
      const detail =
        err instanceof Error ? err.message : "Unknown error";
      message.error(`生成失败: ${detail}`);
    },
  });

  // Persist an accepted generation into the strategy library. The server
  // re-validates the code through the DSL safelist, so an unsafe body is
  // rejected here too (surfaced as a 422 → error toast).
  const saveMutation = useMutation({
    mutationFn: () =>
      strategiesApi
        .save({
          name: saveName.trim(),
          code: result?.code ?? "",
          // Prefer the LLM-authored card; fall back to a provenance card.
          strategy_card: result?.card
            ? (result.card as unknown as Record<string, unknown>)
            : { symbol: GEN_SYMBOL, timeframe: GEN_TIMEFRAME, source_prompt: prompt },
        })
        .then((res) => res.data),
    onSuccess: () => message.success("已保存到策略库"),
    onError: (err: unknown) => {
      const detail = err instanceof Error ? err.message : "Unknown error";
      message.error(`保存失败: ${detail}`);
    },
  });

  const handleSubmit = (): void => {
    if (!prompt.trim()) return;
    mutation.mutate();
  };

  const handleSave = (): void => {
    if (!saveName.trim() || !result?.success) return;
    saveMutation.mutate();
  };

  const generating = mutation.isPending;
  const displayCode = result?.code || fixtureSketch;
  const lastAttempt = result?.attempts[result.attempts.length - 1];

  // Aggregate cost across the whole session for the UI tile.
  const totalUsd = result?.total_usd ?? 0;

  return (
    <TradingPageShell
      eyebrow="Strategy Agent Co-pilot"
      title="AI 策略 Co-pilot"
      description="自然语言假设 → 通过 DSL 安全网 + 防前视的 Python 代码。Co-pilot 调用 LLM 生成、自纠正、限额成本，最多 3 次重试。"
      actions={
        <>
          <Segmented
            value={mode}
            onChange={setMode}
            options={["策略生成", "参数改写", "风险复核"]}
          />
          <Button
            className="btn-gradient"
            type="primary"
            loading={generating}
            onClick={handleSubmit}
          >
            <ThunderboltOutlined /> 生成候选
          </Button>
        </>
      }
      aside={
        <QuantGlowCard
          variant={generating ? "live" : "default"}
          title={<SectionHeader title="生成质量" description="策略生成过程评分" />}
          badge={
            <StatusPill tone={generating ? "ai" : result?.success ? "profit" : "neutral"}>
              {generating ? "Thinking" : result?.success ? "Pass" : "Draft"}
            </StatusPill>
          }
        >
          <div className="trading-list">
            <div>
              <SignalRow
                title="代码安全"
                meta="DSL safelist + 防前视 linter"
              />
              <ScoreRail value={result?.success ? 95 : 50} />
            </div>
            <div>
              <SignalRow
                title="预算使用"
                meta={`总成本 $${totalUsd.toFixed(4)} / 预算 $${(result?.budget_usd ?? 0.05).toFixed(2)}`}
              />
              <ScoreRail
                value={
                  result
                    ? Math.min(
                        100,
                        Math.round((totalUsd / (result.budget_usd ?? 0.05)) * 100),
                      )
                    : 0
                }
              />
            </div>
            <div>
              <SignalRow
                title="尝试次数"
                meta={`已用 ${result?.attempts.length ?? 0} 次 (上限 3)`}
              />
              <ScoreRail
                value={result ? Math.round((result.attempts.length / 3) * 100) : 0}
              />
            </div>
          </div>
        </QuantGlowCard>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard
          className="trading-span-7"
          title={<SectionHeader title="策略假设" description={`当前模式：${mode}`} />}
        >
          <AIAuroraInput
            value={prompt}
            onChange={setPrompt}
            onSubmit={handleSubmit}
            generating={generating}
            rows={7}
            placeholder="输入策略目标、交易品种、时间周期、数据来源和风控约束"
          />
          <div className="trading-toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
            <div className="trading-toolbar-left">
              <StatusPill tone="ai">ValueScan</StatusPill>
              <StatusPill tone="neutral">Backtest</StatusPill>
              <StatusPill tone="profit">Paper first</StatusPill>
            </div>
            <Button onClick={handleSubmit} loading={generating} disabled={!prompt.trim()}>
              生成拆解
            </Button>
          </div>
        </QuantGlowCard>

        <QuantGlowCard
          className="trading-span-5"
          title={
            <SectionHeader
              title="生成代码"
              description={
                result?.success
                  ? `已通过 ${result.attempts.length} 次尝试`
                  : "等待生成"
              }
            />
          }
        >
          <pre className="trading-console" data-testid="strategy-code">
            {displayCode}
          </pre>
          {lastAttempt && lastAttempt.findings.length > 0 ? (
            <div style={{ marginTop: 12, display: "flex", flexWrap: "wrap", gap: 8 }}>
              {lastAttempt.findings.map(findingChip)}
            </div>
          ) : null}
          {result?.success ? (
            <div className="trading-toolbar" style={{ marginTop: 14, marginBottom: 0 }}>
              <div className="trading-toolbar-left" style={{ flex: 1 }}>
                <Input
                  value={saveName}
                  onChange={(event) => setSaveName(event.target.value)}
                  placeholder="为策略命名"
                  maxLength={128}
                  style={{ maxWidth: 280 }}
                  onPressEnter={handleSave}
                />
              </div>
              <Button
                className="btn-gradient"
                type="primary"
                icon={<SaveOutlined />}
                loading={saveMutation.isPending}
                disabled={!saveName.trim()}
                onClick={handleSave}
              >
                保存到库
              </Button>
            </div>
          ) : null}
        </QuantGlowCard>

        <QuantGlowCard className="trading-span-4">
          <MetricTile
            label="实际成本"
            value={totalUsd}
            kind="usd"
            tone={
              result && totalUsd >= (result.budget_usd ?? 0.05) * 0.8
                ? "loss"
                : "neutral"
            }
            subtle={`预算 $${(result?.budget_usd ?? 0.05).toFixed(2)}/会话`}
          />
        </QuantGlowCard>
        <QuantGlowCard className="trading-span-4">
          <MetricTile
            label="尝试次数"
            value={result?.attempts.length ?? 0}
            kind="qty"
            tone={
              result && result.attempts.length >= 3 ? "loss" : "neutral"
            }
            subtle="重试上限 3 次"
          />
        </QuantGlowCard>
        <QuantGlowCard className="trading-span-4">
          <MetricTile
            label="耗时"
            value={`${(result?.elapsed_seconds ?? 0).toFixed(1)}s`}
            kind="plain"
            tone="ai"
            subtle="LLM 调用 + 静态检查"
          />
        </QuantGlowCard>

        {result?.card ? (
          <QuantGlowCard
            className="trading-span-12"
            title={<SectionHeader title="策略卡" description={result.card.name} />}
          >
            <p style={{ color: "var(--qa-text-2)", marginTop: 0 }}>{result.card.thesis}</p>
            <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
              <div style={{ flex: 1, minWidth: 220 }}>
                <strong>有效条件</strong>
                <ul style={{ margin: "6px 0 0", paddingLeft: 18, color: "var(--qa-text-2)" }}>
                  {result.card.valid_when.map((item, i) => (
                    <li key={`${i}-${item}`}>{item}</li>
                  ))}
                </ul>
              </div>
              <div style={{ flex: 1, minWidth: 220 }}>
                <strong>风险清单</strong>
                <ul style={{ margin: "6px 0 0", paddingLeft: 18, color: "var(--qa-text-2)" }}>
                  {result.card.risk_checklist.map((item, i) => (
                    <li key={`${i}-${item}`}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
          </QuantGlowCard>
        ) : null}

        {result && !result.success ? (
          <QuantGlowCard className="trading-span-12">
            <Alert
              type="warning"
              showIcon
              message={
                result.budget_exhausted
                  ? "预算耗尽 — 升级 tier 或精简 prompt 后再试"
                  : "重试 3 次后仍未通过校验 — 请细化 prompt"
              }
              description={
                lastAttempt && lastAttempt.findings.length > 0
                  ? `最后一次尝试触发 ${lastAttempt.findings.length} 条 finding(s)。详见上方代码区。`
                  : "未捕获到具体 finding;请查看审计日志。"
              }
            />
          </QuantGlowCard>
        ) : null}
      </section>
    </TradingPageShell>
  );
}
