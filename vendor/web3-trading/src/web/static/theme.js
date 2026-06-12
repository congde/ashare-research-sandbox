(function () {
    const STORAGE_KEY = "dashboardTheme";
    const LEGACY_KEY = "liveTradingTheme";
    const CHANGE_EVENT = "dashboard-theme-change";

    function readStoredTheme() {
        try {
            const saved = localStorage.getItem(STORAGE_KEY) || localStorage.getItem(LEGACY_KEY);
            return saved === "light" ? "light" : "dark";
        } catch (_) {
            return "dark";
        }
    }

    function getTheme() {
        return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    }

    function updateToggleUi(theme) {
        const lightBtn = document.getElementById("themeLightBtn");
        const darkBtn = document.getElementById("themeDarkBtn");
        lightBtn?.classList.toggle("is-active", theme === "light");
        darkBtn?.classList.toggle("is-active", theme === "dark");
    }

    function applyTheme(theme, persist = true) {
        const next = theme === "light" ? "light" : "dark";
        if (next === "light") {
            document.documentElement.setAttribute("data-theme", "light");
        } else {
            document.documentElement.removeAttribute("data-theme");
        }
        if (persist) {
            try {
                localStorage.setItem(STORAGE_KEY, next);
                localStorage.removeItem(LEGACY_KEY);
            } catch (_) {}
        }
        updateToggleUi(next);
        document.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: { theme: next } }));
    }

    function chartOptions(width, height, extra = {}) {
        const base = typeof ChartTheme !== "undefined"
            ? ChartTheme.baseOptions(width, height, extra)
            : { width, height, ...extra };
        if (getTheme() !== "light") return base;
        return {
            ...base,
            layout: {
                ...(base.layout || {}),
                background: { color: "#ffffff" },
                textColor: "#1a1d26",
            },
            grid: {
                vertLines: { color: "#e8ebf0" },
                horzLines: { color: "#e8ebf0" },
            },
            rightPriceScale: { ...(base.rightPriceScale || {}), borderColor: "#dfe3ea" },
            timeScale: { ...(base.timeScale || {}), borderColor: "#dfe3ea" },
            crosshair: {
                ...(base.crosshair || {}),
                vertLine: { ...(base.crosshair?.vertLine || {}), color: "#b8bec8" },
                horzLine: { ...(base.crosshair?.horzLine || {}), color: "#b8bec8" },
            },
        };
    }

    function bindEvents() {
        document.getElementById("themeLightBtn")?.addEventListener("click", () => applyTheme("light"));
        document.getElementById("themeDarkBtn")?.addEventListener("click", () => applyTheme("dark"));
    }

    function init() {
        applyTheme(readStoredTheme(), false);
        bindEvents();
    }

    window.DashboardTheme = {
        STORAGE_KEY,
        CHANGE_EVENT,
        getTheme,
        applyTheme,
        chartOptions,
        init,
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
