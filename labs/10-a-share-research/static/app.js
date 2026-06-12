const byId = (id) => document.getElementById(id);
const list = (id, items, render = (item) => item) => {
  byId(id).innerHTML = items.map((item) => `<li>${render(item)}</li>`).join("");
};

function renderChart(curve) {
  const values = curve.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 1);
  byId("chart").innerHTML = curve.map((point) => {
    const height = 25 + ((point.equity - min) / span) * 75;
    const ma =
      point.short_ma != null && point.long_ma != null
        ? `短=${point.short_ma} 长=${point.long_ma}`
        : "均线预热中";
    return `<div class="bar" style="height:${height}%" title="${point.date} 权益 ${point.equity} 收盘 ${point.close} ${ma}"></div>`;
  }).join("");
}

function render(payload) {
  const research = payload.research;
  const backtest = payload.backtest;
  byId("warnings").innerHTML = `<strong>边界：</strong> ${payload.warnings.join(" · ")}`;
  byId("company").textContent = research.company;
  list("facts", research.facts, (item) => `${item.claim} <b>[${item.source_id}]</b>`);
  byId("interpretation").textContent = research.interpretation;
  list("unknowns", research.unknowns);
  byId("sources").innerHTML = research.sources.map((source) =>
    `<div class="source"><b>${source.id} · ${source.date}</b><br>${source.title}<p>${source.evidence}</p></div>`
  ).join("");

  const labels = {
    strategy_return_pct: "策略收益率",
    buy_hold_return_pct: "买入持有收益率",
    maximum_drawdown_pct: "最大回撤",
    trade_count: "交易动作数",
    final_equity: "期末模拟权益",
  };
  byId("metrics").innerHTML = Object.entries(backtest.metrics).map(([key, value]) =>
    `<div class="metric"><span>${labels[key]}</span><strong>${value}${key.endsWith("_pct") ? "%" : ""}</strong></div>`
  ).join("");
  renderChart(backtest.curve);
  byId("trades").innerHTML = backtest.trades.length
    ? `<table><tr><th>日期</th><th>动作</th><th>价格</th></tr>${backtest.trades.map((trade) =>
        `<tr><td>${trade.date}</td><td>${trade.action}</td><td>${trade.price}</td></tr>`
      ).join("")}</table>`
    : "<p>该参数组合没有产生交易动作。</p>";
  list("assumptions", backtest.assumptions);
}

async function load(short = 3, long = 7) {
  byId("error").textContent = "";
  const response = await fetch(`/api/report?short=${short}&long=${long}`);
  const payload = await response.json();
  if (!response.ok) {
    byId("error").textContent = payload.error;
    return;
  }
  render(payload);
}

byId("backtest-form").addEventListener("submit", (event) => {
  event.preventDefault();
  load(byId("short").value, byId("long").value);
});
load();
