/**
 * 数据源页面 — 展示所有接入数据的状态与原始面板
 */
class DataSourcesPage {
    constructor() {
        this.state = {
            modules: [],
            moduleSymbol: "BTC-USDT",
            fearGreed: null,
            leadingSector: "",
            sources: {},
        };
        const _el = (id) => document.getElementById(id);
        this.elements = {
            dataSourceGrid: _el("dataSourceGrid"),
            refreshAllSourcesBtn: _el("refreshAllSourcesBtn"),
            dsFearGreed: _el("dsFearGreed"),
            dsSectorLead: _el("dsSectorLead"),
            dsTickerCount: _el("dsTickerCount"),
            dsLastScan: _el("dsLastScan"),
            dsSymbolInput: _el("dsSymbolInput"),
            modulesGrid: _el("modulesGrid"),
            refreshModulesBtn: _el("refreshModulesBtn"),
        };
        if (typeof VsMixin !== "undefined" && VsMixin.VS_ELEMENT_IDS) {
            VsMixin.VS_ELEMENT_IDS.forEach((id) => { this.elements[id] = _el(id); });
        }
        if (typeof DexMixin !== "undefined" && DexMixin.DEX_ELEMENT_IDS) {
            DexMixin.DEX_ELEMENT_IDS.forEach((id) => { this.elements[id] = _el(id); });
        }
    }

    init() {
        this.bindEvents();
        try { this.bindVsEvents(); } catch (e) { console.error(e); }
        try { this.bindDexEvents(); } catch (e) { console.error(e); }
        this.refreshAll();
    }

    bindEvents() {
        if (this.elements.refreshAllSourcesBtn) {
            this.elements.refreshAllSourcesBtn.addEventListener("click", () => this.refreshAll());
        }
        if (this.elements.refreshModulesBtn) {
            this.elements.refreshModulesBtn.addEventListener("click", () => this.loadModulesData());
        }
        if (this.elements.dsSymbolInput) {
            this.elements.dsSymbolInput.addEventListener("change", () => this.onSymbolChange());
            this.elements.dsSymbolInput.addEventListener("keydown", (e) => {
                if (e.key === "Enter") this.onSymbolChange();
            });
        }
    }

    getActiveSymbol() {
        const raw = (this.elements.dsSymbolInput?.value || "BTC").trim().toUpperCase();
        return raw.split("-")[0] || "BTC";
    }

    onSymbolChange() {
        const sym = this.getActiveSymbol();
        this.loadVsFundData(sym);
        this.refreshDexData(sym);
        this.loadModulesData();
    }

    async refreshAll() {
        await Promise.all([
            this.probeSources(),
            this.loadMarketContext(),
            this.loadVsAiPicks(),
            this.loadVsSectorFund(),
            this.loadVsFundData(this.getActiveSymbol()),
            this.loadDexTrending(),
            this.refreshDexData(this.getActiveSymbol()),
            this.loadModulesData(),
        ]);
    }

    async probeSources() {
        const checks = [
            { id: "kucoin", name: "KuCoin 行情", desc: "现货 Tickers / K线", probe: () => fetch("/api/market/tickers?quote=USDT&limit=5") },
            { id: "valuescan", name: "ValueScan", desc: "AI 智选 · 资金 · 板块", probe: () => fetch("/api/dashboard/vs/ai-picks") },
            { id: "dexscan", name: "DexScan", desc: "DEX 概览 · 热门代币", probe: () => fetch("/api/dashboard/dex/trending?chain=solana&limit=5") },
            { id: "feargreed", name: "恐贪指数", desc: "alternative.me", probe: () => fetch("/api/dashboard/onchain?symbol=BTC&limit=1") },
            { id: "scanner", name: "机会扫描", desc: "Rule + ValueScan 信号", probe: () => fetch("/api/dashboard/opportunity-scan?topK=1&maxSymbols=5") },
            { id: "skills", name: "Skills 模块", desc: "KuCoin / 链上 / 新闻", probe: () => fetch("/api/skills/modules?symbol=BTC-USDT") },
        ];
        const results = await Promise.all(checks.map(async (c) => {
            const t0 = Date.now();
            try {
                const resp = await c.probe();
                const data = await this.parseJsonResponse(resp);
                const ok = resp.ok && data.ok !== false;
                return { ...c, ok, ms: Date.now() - t0, detail: ok ? this._sourceDetail(c.id, data) : (data.message || "不可用") };
            } catch (e) {
                return { ...c, ok: false, ms: Date.now() - t0, detail: e.message };
            }
        }));
        this.state.sources = Object.fromEntries(results.map((r) => [r.id, r]));
        this.renderSourceGrid(results);
    }

    _sourceDetail(id, data) {
        if (id === "kucoin") return `${(data.tickers || []).length} 交易对`;
        if (id === "valuescan") {
            const n = (data.chance || []).length + (data.funds || []).length + (data.risk || []).length;
            return `${n} 条智选`;
        }
        if (id === "dexscan") return `${(data.tokens || []).length} trending`;
        if (id === "feargreed") {
            const fg = (data.marketSentiment || {}).fearGreed || {};
            return fg.value != null ? `指数 ${fg.value}` : "已连接";
        }
        if (id === "scanner") return `${(data.opportunities || []).length} 条机会`;
        if (id === "skills") return `${(data.modules || []).length} 个模块`;
        return "已连接";
    }

    renderSourceGrid(results) {
        if (!this.elements.dataSourceGrid) return;
        this.elements.dataSourceGrid.innerHTML = results.map((r) => `
            <article class="ds-source-card ${r.ok ? "ds-ok" : "ds-error"}">
                <div class="ds-source-head">
                    <span class="ds-source-dot"></span>
                    <h3>${this.escapeHtml(r.name)}</h3>
                </div>
                <p class="ds-source-desc">${this.escapeHtml(r.desc)}</p>
                <p class="ds-source-detail">${this.escapeHtml(String(r.detail || ""))}</p>
                <span class="ds-source-latency tabnum">${r.ms}ms</span>
            </article>
        `).join("");
    }

    async loadMarketContext() {
        try {
            const [onchain, tickers, sector] = await Promise.all([
                fetch("/api/dashboard/onchain?symbol=BTC&limit=1").then((r) => this.parseJsonResponse(r)),
                fetch("/api/market/tickers?quote=USDT&limit=300").then((r) => this.parseJsonResponse(r)),
                fetch("/api/dashboard/vs/sector-fund?trade_type=1").then((r) => this.parseJsonResponse(r)),
            ]);
            if (onchain.ok) {
                this.state.fearGreed = (onchain.marketSentiment || {}).fearGreed || {};
                this._renderFearGreed();
            }
            if (tickers.ok && this.elements.dsTickerCount) {
                this.elements.dsTickerCount.textContent = `${(tickers.tickers || []).length}`;
            }
            if (sector.ok) {
                const sectors = sector.sectors || [];
                const getInflow = (s, r) => {
                    const item = (s.categoriesTradeDataList || []).find((t) => t.timeRange === r);
                    return item ? Number(item.tradeInflow || 0) : 0;
                };
                const top = [...sectors].sort((a, b) => getInflow(b, "h1") - getInflow(a, "h1"))[0];
                this.state.leadingSector = top ? (top.tagsSimplified || top.tag || "") : "";
                if (this.elements.dsSectorLead) {
                    const el = this.elements.dsSectorLead.querySelector(".ds-context-value");
                    if (el) el.textContent = this.state.leadingSector || "-";
                }
            }
        } catch (_e) { /* optional */ }
        try {
            const scan = await fetch("/api/dashboard/opportunity-scan?topK=1&maxSymbols=5");
            const data = await this.parseJsonResponse(scan);
            if (data.ok && data.scanTime && this.elements.dsLastScan) {
                const d = new Date(data.scanTime);
                this.elements.dsLastScan.textContent = d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
            }
        } catch (_e) { /* optional */ }
    }

    _renderFearGreed() {
        if (!this.elements.dsFearGreed) return;
        const el = this.elements.dsFearGreed.querySelector(".ds-context-value");
        const fg = this.state.fearGreed || {};
        if (!el) return;
        el.textContent = fg.value != null ? `${fg.value}${fg.label ? ` · ${fg.label}` : ""}` : "-";
    }

    getPrimarySymbol() {
        const sym = this.getActiveSymbol();
        return `${sym}-USDT`;
    }

    async loadModulesData() {
        const symbol = this.getPrimarySymbol();
        this.state.moduleSymbol = symbol;
        if (!this.elements.modulesGrid) return;
        this.elements.modulesGrid.innerHTML = `<div class="module-data">加载 ${symbol} ...</div>`;
        try {
            const resp = await fetch(`/api/skills/modules?symbol=${encodeURIComponent(symbol)}`);
            const data = await this.parseJsonResponse(resp);
            if (!resp.ok || !data.ok) throw new Error(data.message || "加载失败");
            this.state.modules = data.modules || [];
            this.renderModules();
        } catch (error) {
            this.elements.modulesGrid.innerHTML = `<div class="module-data">加载失败: ${error.message}</div>`;
        }
    }

    renderModules() {
        const modules = this.state.modules || [];
        if (!this.elements.modulesGrid) return;
        if (!modules.length) {
            this.elements.modulesGrid.innerHTML = `<div class="module-data">暂无模块</div>`;
            return;
        }
        this.elements.modulesGrid.innerHTML = modules.map((mod) => {
            const status = mod.status || "unknown";
            const cls = status === "ok" ? "module-ok" : status === "unavailable" ? "module-warn" : "module-error";
            const dataText = status === "ok" ? this.toPrettySummary(mod.data) : (mod.note || mod.error || "-");
            return `<article class="module-card"><h4>${mod.name || "?"}</h4><div class="module-meta ${cls}">${status.toUpperCase()} · ${mod.latencyMs || 0}ms</div><div class="module-data">${dataText}</div></article>`;
        }).join("");
    }

    toPrettySummary(data) {
        if (!data || typeof data !== "object") return "-";
        const raw = JSON.stringify(data, null, 2);
        return raw.length > 900 ? `${raw.slice(0, 900)} ...` : raw;
    }

    async parseJsonResponse(response) {
        const text = await response.text();
        if (!text.trim()) return {};
        return JSON.parse(text);
    }
}

if (typeof DashboardUtils !== "undefined") {
    Object.keys(DashboardUtils).forEach((k) => { DataSourcesPage.prototype[k] = DashboardUtils[k]; });
}
if (typeof VsMixin !== "undefined") {
    Object.keys(VsMixin).forEach((k) => {
        if (k === "VS_ELEMENT_IDS") return;
        DataSourcesPage.prototype[k] = VsMixin[k];
    });
}
if (typeof DexMixin !== "undefined") {
    Object.keys(DexMixin).forEach((k) => {
        if (k === "DEX_ELEMENT_IDS") return;
        DataSourcesPage.prototype[k] = DexMixin[k];
    });
}

document.addEventListener("DOMContentLoaded", () => new DataSourcesPage().init());
