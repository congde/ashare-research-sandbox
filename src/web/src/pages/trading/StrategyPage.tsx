import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Space } from "antd";
import { validateStrategy } from "../../api";
import type { StrategyValidationResult } from "../../types";
import { QuantGlowCard, SectionHeader, SignalRow, StatusPill, TradingPageShell } from "./TradingPageShell";

const DEFAULT_CODE = `def on_tick(ctx, candle):
    short = sum(ctx.history[-3:]) / 3
    long = sum(ctx.history[-7:]) / 7
    if short > long:
        return "BUY"
    return "SELL"
`;

export default function StrategyPage() {
  const navigate = useNavigate();
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
      description="在策略代码进入回测前，先检查 import 安全与前视偏差。通过后进入 /backtests 做历史模拟，再到 /risk 核对拒绝。"
      actions={
        <Space>
          <Button onClick={() => navigate("/backtests")}>去策略回测</Button>
          <Button onClick={() => navigate("/risk")}>去风控中心</Button>
          <StatusPill tone={result?.valid ? "profit" : "ai"}>
            {result ? (result.valid ? "通过" : "待修复") : "等待校验"}
          </StatusPill>
        </Space>
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

        <QuantGlowCard
          className="trading-span-12"
          title={<SectionHeader title="下一步：回测证据链" description="docs/samples/backtest-teaching-guide.md" />}
        >
          <div className="trading-list">
            <SignalRow title="回测 = 历史模拟，不是真实下单" meta="第 18–21 讲" />
            <SignalRow title="策略 DSL 通过 → /backtests 运行 → /risk 复核" meta="第 26 讲页面路径" />
            <SignalRow title="CLI：py scripts/backtest_lab.py compare" meta="五策略同屏比较" />
          </div>
        </QuantGlowCard>
      </section>
    </TradingPageShell>
  );
}
