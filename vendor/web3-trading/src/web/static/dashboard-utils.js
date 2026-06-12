/**
 * Shared utility methods used across all pages.
 * Loaded before page-specific JS — provides DashboardUtils for prototype merging.
 */

const DashboardUtils = {
    escapeHtml(s) {
        const div = document.createElement("div");
        div.textContent = s;
        return div.innerHTML;
    },

    formatNumber(value) {
        const number = Number(value || 0);
        if (!Number.isFinite(number)) return "-";
        if (Math.abs(number) >= 1e9) return `${(number / 1e9).toFixed(2)}B`;
        if (Math.abs(number) >= 1e6) return `${(number / 1e6).toFixed(2)}M`;
        if (Math.abs(number) >= 1e3) return `${(number / 1e3).toFixed(2)}K`;
        if (Math.abs(number) >= 1) return number.toFixed(4);
        return number.toPrecision(4);
    },

    formatPercent(value, digits = 1) {
        const n = Number(value);
        if (!Number.isFinite(n)) return "-";
        return n.toFixed(digits);
    },

    sanitizeGateText(text) {
        if (text == null || text === "") return "";
        return String(text).replace(/\d+\.\d{4,}/g, (m) => {
            const n = parseFloat(m);
            return Number.isFinite(n) ? n.toFixed(1) : m;
        });
    },

    GATE_STEP_ORDER: ["structure", "flow", "quant", "executable"],

    GATE_STEP_LABELS: {
        structure: "多周期",
        flow: "LLM因子",
        quant: "量化",
        executable: "可执行",
    },

    shortenAddr(addr, head = 6, tail = 4) {
        if (!addr || addr.length <= head + tail + 3) return addr || "";
        return addr.slice(0, head) + "..." + addr.slice(-tail);
    },

    async parseJsonResponse(response) {
        const text = await response.text();
        if (!text.trim()) return {};
        try {
            return JSON.parse(text);
        } catch (_e) {
            throw new Error(`接口返回非 JSON (${response.status}): ${text.slice(0, 160)}`);
        }
    },

    computeVolatility(item) {
        const last = Number(item.last || 0);
        const high = Number(item.high || 0);
        const low = Number(item.low || 0);
        if (!Number.isFinite(last) || last <= 0) return 0;
        return (high - low) / last;
    },

    renderMetricCard(label, value) {
        return `<div class="signal-metric-card"><div class="signal-metric-label">${this.escapeHtml(label)}</div><div class="signal-metric-value">${this.escapeHtml(String(value ?? "-"))}</div></div>`;
    },

    formatModelName(model) {
        const value = String(model || "");
        if (value.includes("deepseek-v4-flash")) return "DeepSeek V4 Flash";
        if (value.includes("deepseek-v4-pro")) return "DeepSeek V4 Pro";
        if (value.includes("deepseek-v4")) return "DeepSeek V4";
        if (value.includes("deepseek-chat")) return "DeepSeek Chat (V3)";
        if (value.includes("deepseek-reasoner")) return "DeepSeek Reasoner";
        if (value.includes("Qwen3.5-27B")) return "Qwen 3.5 27B";
        return value || "-";
    },

    toChineseDisplay(type, value) {
        const text = String(value ?? "").trim();
        if (!text) return "-";
        const map = {
            bias: { bullish: "偏多", bearish: "偏空", neutral: "中性" },
            direction: { bullish: "偏多", bearish: "偏空", neutral: "中性" },
            marketState: {
                trend_continuation: "趋势延续",
                trend_continuation_near_resistance: "趋势延续但接近压力",
                range_rebound: "区间反弹",
                range_breakdown_risk: "区间下破风险",
                breakout_confirmation: "突破确认",
                false_breakout_risk: "假突破风险",
                uncertain: "方向尚不明朗",
            },
            horizon: { intraday: "日内", intraday_swing: "日内到波段", swing: "波段" },
            executionReadiness: {
                ready: "可执行",
                watch_pullback: "等待回踩",
                wait_breakout: "等待突破确认",
                avoid: "暂不参与",
                wait: "继续观察",
            },
            strength: { weak: "较弱", medium: "中等", strong: "较强" },
            severity: { low: "低", medium: "中", high: "高" },
            scenario: { bull: "乐观情景", base: "基准情景", bear: "悲观情景" },
        };
        const normalized = text.toLowerCase();
        const mapped = map[type]?.[normalized];
        if (mapped) return mapped;
        return /[\u4e00-\u9fa5]/.test(text) ? text : text.replace(/_/g, " ");
    },

    _isGateSignalItem(sig) {
        return sig && sig.participatesInGate !== false && !sig.displayOnly;
    },

    /** 入场门禁列表：仅四步（多周期 / LLM 因子 / 量化 / 可执行） */
    buildFiveSignalsList(row) {
        if (Array.isArray(row.fiveSignals) && row.fiveSignals.length) {
            return row.fiveSignals.filter((s) => this._isGateSignalItem(s));
        }
        const dimShort = { bullish: "偏多", bearish: "偏空", neutral: "中性" };
        const align = row.fiveSignalAlignment || row.entryGateAlignment || {};
        const gateKeys = new Set(
            align.gateDimensions || ["structure", "flow", "quant", "executable"]
        );
        const order = [
            ["structure", "多周期"],
            ["flow", "LLM因子"],
            ["quant", "量化"],
            ["executable", "可执行"],
        ];
        const dims = align.dimensions || {};
        const gateNotes = align.gateNotes || {};
        const quant = row.quantFactors || {};

        return order.map(([key, name]) => {
            if (!gateKeys.has(key)) return null;

            let direction = dims[key] || "neutral";
            let score = null;
            let hint = gateNotes[key] || align[`${key}Note`] || "";

            if (key === "structure") {
                const tf = align.timeframeDirections || {};
                const parts = [];
                ["15m", "1h", "4h", "1d"].forEach((lbl) => {
                    const d = tf[lbl];
                    if (d === "bullish") parts.push(`${lbl}:多`);
                    else if (d === "bearish") parts.push(`${lbl}:空`);
                });
                if (parts.length) hint = hint || parts.join(" · ");
                hint = hint || align.structureNote || "K 线四周期";
            } else if (key === "flow") {
                hint = hint || align.flowNote || "技术/盘面/倾向";
            } else if (key === "quant") {
                direction = dims.quant || direction;
                if (quant.available && quant.aggregateScore != null) {
                    score = Number(quant.aggregateScore) * 100;
                }
                const statusCn = {
                    confirm: "已确认",
                    neutral: "中性区",
                    skipped: "未参与",
                    veto: "已否决",
                };
                const st = align.quantStatus || "";
                if (st && !hint) hint = statusCn[st] || st;
                hint = hint || align.quantNote || "量化管线";
            } else if (key === "executable") {
                hint = hint || align.executableNote || "ready · 计划 R:R";
            }

            return {
                key,
                name,
                direction,
                label: dimShort[direction] || direction,
                score: score != null && !Number.isNaN(score) ? Number(score) : null,
                hint: String(hint || "").slice(0, 120),
                participatesInGate: true,
                displayOnly: false,
            };
        }).filter(Boolean);
    },

    formatFiveSignalsHtml(row, { gate = false } = {}) {
        const signals = this.buildFiveSignalsList(row);
        if (!signals.length) return "";
        const align = row.fiveSignalAlignment || row.entryGateAlignment || {};
        let head = gate
            ? '<div class="live-gate-five__head">入场门禁</div>'
            : '<div class="live-gate-five__head">入场门禁</div>';
        if (!gate) {
            const ok = !!align.aligned;
            const cls = ok ? "signal-chip-positive" : "signal-chip-warning";
            const dimCn =
                row.fiveSignalAlignmentLabel ||
                Object.entries(align.dimensions || {})
                    .filter(([k]) => (align.gateDimensions || []).includes(k))
                    .map(([k, v]) => `${k}:${v}`)
                    .join(" · ");
            head =
                `<div class="live-gate-five__head">入场门禁 · ` +
                `<span class="signal-chip ${cls}">${ok ? "已对齐" : "未对齐"}</span></div>` +
                (align.reason
                    ? `<div class="signal-inline-note">${this.escapeHtml(align.reason)}</div>`
                    : "") +
                (dimCn && !row.fiveSignalAlignmentLabel
                    ? `<div class="signal-inline-note">${this.escapeHtml(dimCn)}</div>`
                    : "") +
                (row.fiveSignalAlignmentLabel
                    ? `<div class="signal-inline-note">${this.escapeHtml(row.fiveSignalAlignmentLabel)}</div>`
                    : "");
        }
        const items = signals.map((sig) => {
            const dirClass =
                sig.direction === "bullish"
                    ? "signal-buy"
                    : sig.direction === "bearish"
                      ? "signal-sell"
                      : "";
            const scorePart =
                sig.score != null && !Number.isNaN(sig.score)
                    ? ` <span class="live-gate-five__score">(${sig.score >= 0 ? "+" : ""}${Number(sig.score).toFixed(1)})</span>`
                    : "";
            const hintPart = sig.hint
                ? `<span class="live-gate-five__hint">${this.escapeHtml(sig.hint)}</span>`
                : "";
            return (
                `<div class="live-gate-five__item ${dirClass}">` +
                `<span class="live-gate-five__name">${this.escapeHtml(sig.name)}</span>` +
                `<span class="live-gate-five__dir">${this.escapeHtml(sig.label)}</span>${scorePart}${hintPart}` +
                `</div>`
            );
        });
        return `${head}<div class="live-gate-five">${items.join("")}</div>`;
    },

    _gateStepState(key, align) {
        const order = this.GATE_STEP_ORDER;
        const idx = order.indexOf(key);
        if (idx < 0) return "pending";
        if (align.aligned || align.side) return "pass";
        const failed = align.failedGate;
        if (!failed) return idx === 0 ? "fail" : "pending";
        const failIdx = order.indexOf(failed);
        if (failIdx < 0) return "pending";
        if (idx < failIdx) return "pass";
        if (idx === failIdx) return "fail";
        return "skip";
    },

    _gateStepStatusText(state, sig) {
        if (state === "pass") return "通过";
        if (state === "skip") return "跳过";
        if (state === "fail") {
            if (sig.direction === "bullish") return "偏多";
            if (sig.direction === "bearish") return "偏空";
            return "未过";
        }
        return "—";
    },

    formatEntryGateStepsHtml(row) {
        const align = row.fiveSignalAlignment || row.entryGateAlignment || {};
        const signals = this.buildFiveSignalsList(row);
        if (!signals.length) return "";
        const items = signals.map((sig) => {
            const key = sig.key;
            const state = this._gateStepState(key, align);
            const idx = this.GATE_STEP_ORDER.indexOf(key) + 1;
            const label = this.GATE_STEP_LABELS[key] || sig.name || key;
            const status = this._gateStepStatusText(state, sig);
            const score =
                sig.score != null && !Number.isNaN(sig.score) && key === "quant"
                    ? ` ${sig.score >= 0 ? "+" : ""}${Number(sig.score).toFixed(1)}`
                    : "";
            const showHint = state === "fail" || (state === "skip" && sig.hint);
            const hint = showHint ? this.sanitizeGateText(sig.hint).slice(0, 96) : "";
            const hintHtml = hint
                ? `<p class="live-gate-step__hint">${this.escapeHtml(hint)}</p>`
                : "";
            return (
                `<li class="live-gate-step live-gate-step--${state}">` +
                `<span class="live-gate-step__n">${idx}</span>` +
                `<span class="live-gate-step__label">${this.escapeHtml(label)}</span>` +
                `<span class="live-gate-step__status">${this.escapeHtml(status)}${score ? `<span class="live-gate-step__score">${score}</span>` : ""}</span>` +
                `${hintHtml}</li>`
            );
        });
        return `<ol class="live-gate-steps">${items.join("")}</ol>`;
    },

    formatEntryGateCellHtml(row) {
        const align = row.fiveSignalAlignment || row.entryGateAlignment || {};
        const passed = !!(row.gateSide || align.aligned);
        const side = row.gateSide || align.side;
        const failedLabels = {
            structure: "①多周期",
            flow: "②LLM因子",
            quant: "③量化",
            executable: "④可执行",
        };
        let badgeClass = "live-gate-cell__badge--blocked";
        let badgeText = "未通过";
        if (side === "buy" || (passed && align.side === "buy")) {
            badgeClass = "live-gate-cell__badge--long";
            badgeText = "开多 · 通过";
        } else if (side === "sell" || (passed && align.side === "sell")) {
            badgeClass = "live-gate-cell__badge--short";
            badgeText = "开空 · 通过";
        } else if (passed) {
            badgeClass = "live-gate-cell__badge--ok";
            badgeText = "已通过";
        }

        const parts = [`<div class="live-gate-cell__badge ${badgeClass}">${badgeText}</div>`];

        const reasonRaw = align.reason || row.fiveSignalAlignmentLabel || "";
        if (!passed && reasonRaw) {
            const step = align.failedGate ? failedLabels[align.failedGate] || "" : "";
            const reason = this.sanitizeGateText(reasonRaw);
            parts.push(
                `<p class="live-gate-cell__reason">${step ? `<span class="live-gate-cell__step">${this.escapeHtml(step)}</span> ` : ""}${this.escapeHtml(reason)}</p>`
            );
        }

        const steps = this.formatEntryGateStepsHtml(row);
        if (steps) parts.push(steps);

        const meta = [];
        const conf = row.confidence;
        if (conf != null && Number.isFinite(Number(conf)) && !passed) {
            meta.push(`置信 ${this.formatPercent(conf)}%`);
        }
        const gateReason = this.sanitizeGateText(String(row.gateReason || "").trim());
        const alignReason = this.sanitizeGateText(String(align.reason || "").trim());
        if (gateReason && gateReason !== alignReason) {
            meta.push(gateReason.length > 48 ? `${gateReason.slice(0, 48)}…` : gateReason);
        }
        const readiness = String(row.executionReadiness || "").trim();
        if (readiness && readiness.toLowerCase() !== "ready") {
            const rd =
                readiness.includes("观察") || readiness.includes("observe")
                    ? "继续观察"
                    : readiness;
            meta.push(rd);
        }
        if (meta.length) {
            parts.push(`<p class="live-gate-cell__meta">${this.escapeHtml(meta.join(" · "))}</p>`);
        }

        const cellState = passed ? "pass" : "blocked";
        return `<div class="live-gate-cell live-gate-cell--${cellState}">${parts.join("")}</div>`;
    },
};

// ChartTheme / ChartIndicators / KlineChartStack live in /shared/chart/* (see partials/chart_assets.html)
