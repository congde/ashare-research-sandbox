/**
 * Binds optional indicator checkboxes to a KlineChartStack instance.
 */
(function (global) {
    const STORAGE_KEY = "cryptoquantx_kline_indicators";

    class KlineIndicatorControls {
        constructor(toolbarEl, stack, options = {}) {
            this.toolbarEl = toolbarEl;
            this.stack = stack;
            this.storageKey = options.storageKey || STORAGE_KEY;
            this.onChange = typeof options.onChange === "function" ? options.onChange : null;
            this._inputs = [];
        }

        static loadSaved(defaults) {
            try {
                const raw = localStorage.getItem(STORAGE_KEY);
                if (!raw) return { ...defaults };
                return { ...defaults, ...JSON.parse(raw) };
            } catch (_err) {
                return { ...defaults };
            }
        }

        static save(indicators) {
            try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(indicators));
            } catch (_err) {
                /* ignore quota errors */
            }
        }

        bind() {
            if (!this.toolbarEl || !this.stack) return;
            const defaults = global.KLINE_DEFAULT_INDICATORS || {};
            const saved = KlineIndicatorControls.loadSaved(defaults);
            this.stack.setIndicators(saved);

            this._inputs = Array.from(this.toolbarEl.querySelectorAll("input[data-ind]"));
            this._inputs.forEach((input) => {
                const key = input.getAttribute("data-ind");
                if (!key || !(key in saved)) return;
                input.checked = !!saved[key];
                input.addEventListener("change", () => this.handleChange());
            });
        }

        handleChange() {
            const partial = {};
            this._inputs.forEach((input) => {
                const key = input.getAttribute("data-ind");
                if (key) partial[key] = input.checked;
            });
            this.stack.setIndicators(partial);
            KlineIndicatorControls.save(this.stack.getIndicators());
            if (this.onChange) this.onChange(this.stack.getIndicators());
        }
    }

    global.KlineIndicatorControls = KlineIndicatorControls;
})(typeof window !== "undefined" ? window : globalThis);
