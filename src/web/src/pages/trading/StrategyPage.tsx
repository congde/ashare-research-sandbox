import { useState } from "react";
import { Button } from "antd";
import { validateStrategy } from "../../api";
import type { StrategyValidationResult } from "../../types";
import { QuantGlowCard, SectionHeader, StatusPill, TradingPageShell } from "./TradingPageShell";

const DEFAULT_CODE = `def on_tick(ctx, candle):
    short = sum(ctx.history[-3:]) / 3
    long = sum(ctx.history[-7:]) / 7
    if short > long:
        return "BUY"
    return "SELL"
`;

export default function StrategyPage() {
  const [code, setCode] = useState(DEFAULT_CODE);
  const [result, setResult] = useState<StrategyValidationResult | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleValidate() {
    setLoading(true);
    try {
      setResult(await validateStrategy(code));
    } catch (error) {
      setResult({
        valid: false,
        validation: { valid: false, errors: [] },
        lookahead: { clean: false, findings: [] },
        source: "strategy_engine/dsl",
        error: error instanceof Error ? error.message : "校验失败",
      });
    } finally {
      setLoading(false);
    }
  }

  return (
    <TradingPageShell
      eyebrow="Strategy DSL"
      title="受限策略 DSL 校验"
      description="在策略代码进入回测前，先检查 import 安全与前视偏差。接口来自 ai-trading strategy_engine/dsl。"
      actions={
        <StatusPill tone={result?.valid ? "profit" : "ai"}>
          {result ? (result.valid ? "通过" : "待修复") : "等待校验"}
        </StatusPill>
      }
    >
      <section className="trading-grid">
        <QuantGlowCard className="trading-span-12">
          <SectionHeader title="策略代码" description="POST /api/validate-strategy" />
          <textarea
            rows={10}
            spellCheck={false}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            style={{
              width: "100%",
              marginBottom: 14,
              padding: 14,
              borderRadius: 8,
              border: "1px solid var(--qa-line-subtle)",
              background: "rgba(4, 8, 18, 0.78)",
              color: "var(--qa-text-1)",
              fontFamily: "var(--qa-font-mono)",
            }}
          />
          <Button className="btn-gradient" type="primary" loading={loading} onClick={() => void handleValidate()}>
            校验策略代码
          </Button>
          <pre
            style={{
              marginTop: 16,
              padding: 16,
              borderRadius: 8,
              border: "1px solid rgba(148, 163, 184, 0.2)",
              background: "rgba(4, 8, 18, 0.78)",
              color: "var(--qa-text-2)",
              overflow: "auto",
              whiteSpace: "pre-wrap",
            }}
          >
            {result ? JSON.stringify(result, null, 2) : "等待校验..."}
          </pre>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
