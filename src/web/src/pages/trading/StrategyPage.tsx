import type { ReactElement, UIEvent } from "react";
import { useMemo, useRef, useState } from "react";
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

const PYTHON_KEYWORDS = new Set([
  "and",
  "as",
  "assert",
  "break",
  "class",
  "continue",
  "def",
  "elif",
  "else",
  "except",
  "False",
  "finally",
  "for",
  "from",
  "if",
  "import",
  "in",
  "is",
  "lambda",
  "None",
  "not",
  "or",
  "pass",
  "raise",
  "return",
  "True",
  "try",
  "while",
  "with",
  "yield",
]);

const PYTHON_BUILTINS = new Set(["abs", "bool", "dict", "float", "int", "len", "list", "max", "min", "range", "round", "str", "sum", "tuple"]);

function highlightPython(code: string) {
  let key = 0;
  const nodes: Array<string | ReactElement> = [];
  const pattern =
    /(#.*$)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(\b\d+(?:\.\d+)?\b)|(\b[A-Za-z_][A-Za-z0-9_]*\b)/gm;
  let cursor = 0;

  for (const match of code.matchAll(pattern)) {
    const index = match.index ?? 0;
    if (index > cursor) {
      nodes.push(code.slice(cursor, index));
    }
    const value = match[0];
    const className = match[1]
      ? "syntax-comment"
      : match[2]
        ? "syntax-string"
        : match[3]
          ? "syntax-number"
          : PYTHON_KEYWORDS.has(value)
            ? "syntax-keyword"
            : PYTHON_BUILTINS.has(value)
              ? "syntax-builtin"
              : "";

    nodes.push(
      className ? (
        <span className={className} key={`syntax-${key++}`}>
          {value}
        </span>
      ) : (
        value
      ),
    );
    cursor = index + value.length;
  }
  if (cursor < code.length) {
    nodes.push(code.slice(cursor));
  }
  return nodes;
}

export default function StrategyPage() {
  const navigate = useNavigate();
  const highlightRef = useRef<HTMLPreElement | null>(null);
  const [code, setCode] = useState(DEFAULT_CODE);
  const [result, setResult] = useState<StrategyValidationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const lineNumbers = useMemo(
    () =>
      Array.from({ length: Math.max(code.split("\n").length, 10) }, (_, index) => index + 1).join("\n"),
    [code],
  );
  const highlightedCode = useMemo(() => highlightPython(code), [code]);

  function handleEditorScroll(event: UIEvent<HTMLTextAreaElement>) {
    if (!highlightRef.current) {
      return;
    }
    highlightRef.current.scrollTop = event.currentTarget.scrollTop;
    highlightRef.current.scrollLeft = event.currentTarget.scrollLeft;
  }

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
        <QuantGlowCard
          className="trading-span-12 strategy-editor-card"
          title={<SectionHeader title="策略代码" description="POST /api/validate-strategy" />}
        >
          <div className="strategy-code-shell">
            <div className="strategy-code-topbar">
              <span>Python DSL</span>
              <strong>{code.split("\n").length} 行</strong>
            </div>
            <div className="strategy-code-editor">
              <pre aria-hidden="true" className="strategy-code-gutter">
                {lineNumbers}
              </pre>
              <div className="strategy-code-input-stack">
                <pre ref={highlightRef} aria-hidden="true" className="strategy-code-highlight">
                  {highlightedCode}
                </pre>
                <textarea
                  rows={12}
                  spellCheck={false}
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                  onScroll={handleEditorScroll}
                  aria-label="策略代码编辑器"
                />
              </div>
            </div>
          </div>
          <div className="strategy-editor-actions">
            <Button className="btn-gradient" type="primary" loading={loading} onClick={() => void handleValidate()}>
              校验策略代码
            </Button>
            <Button onClick={() => setCode(DEFAULT_CODE)}>恢复示例</Button>
          </div>
          <div className="strategy-result-panel">
            <div className="strategy-result-header">
              <span>校验结果</span>
              <StatusPill tone={result?.valid ? "profit" : result ? "loss" : "neutral"}>
                {result ? (result.valid ? "valid" : "invalid") : "idle"}
              </StatusPill>
            </div>
            <pre>{result ? JSON.stringify(result, null, 2) : "等待校验..."}</pre>
          </div>
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
