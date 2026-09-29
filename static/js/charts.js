// Chart rendering. Colours come from CSS custom properties so every chart
// follows the active theme and light/dark mode, and re-renders when they change.
(function () {
    "use strict";
    if (!window.Chart) return;

    var body = document.body;
    var grouping = body.getAttribute("data-grouping") === "indian" ? "en-IN" : "en-US";
    var symbol = body.getAttribute("data-currency-symbol") || "₹";
    var charts = {};

    var probe = document.createElement("span");
    probe.style.display = "none";
    document.body.appendChild(probe);
    var colorCtx = document.createElement("canvas").getContext("2d");

    function cssVar(name) {
        return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    }

    // Resolve a colour token (which may be a color-mix() expression) to plain hex/rgba
    // so Chart.js can parse it for hover shading.
    function cssColor(name) {
        probe.style.color = "";
        probe.style.color = "var(" + name + ")";
        var computed = getComputedStyle(probe).color;
        colorCtx.fillStyle = "#000";
        colorCtx.fillStyle = computed;
        return colorCtx.fillStyle;
    }

    function money(cents, compact) {
        var value = cents / 100;
        if (compact && Math.abs(value) >= 1000) {
            return symbol + new Intl.NumberFormat(grouping, { notation: "compact", maximumFractionDigits: 1 }).format(value);
        }
        return symbol + new Intl.NumberFormat(grouping, { maximumFractionDigits: 0 }).format(value);
    }

    function palette() {
        return {
            s1: cssColor("--series-1"),
            s2: cssColor("--series-2"),
            accent: cssColor("--accent-fill"),
            ink: cssColor("--ink"),
            muted: cssColor("--ink-muted"),
            grid: cssColor("--grid"),
            surface: cssColor("--paper-card"),
            critical: cssColor("--danger")
        };
    }

    function applyDefaults(p) {
        Chart.defaults.font.family = cssVar("--font-body") || "system-ui, sans-serif";
        Chart.defaults.font.size = 12;
        Chart.defaults.color = p.muted;
        Chart.defaults.borderColor = p.grid;
        Chart.defaults.maintainAspectRatio = false;
        Chart.defaults.animation.duration = 400;
        Chart.defaults.plugins.legend.labels.usePointStyle = true;
        Chart.defaults.plugins.legend.labels.pointStyle = "rectRounded";
        Chart.defaults.plugins.legend.labels.boxWidth = 10;
        Chart.defaults.plugins.legend.labels.boxHeight = 10;
        Chart.defaults.plugins.legend.labels.color = p.ink;
        Chart.defaults.plugins.legend.align = "start";
        Chart.defaults.plugins.tooltip.backgroundColor = p.ink;
        Chart.defaults.plugins.tooltip.titleColor = p.surface;
        Chart.defaults.plugins.tooltip.bodyColor = p.surface;
        Chart.defaults.plugins.tooltip.padding = 10;
        Chart.defaults.plugins.tooltip.cornerRadius = 6;
        Chart.defaults.plugins.tooltip.boxPadding = 4;
    }

    function moneyAxis(p, extra) {
        return Object.assign({
            beginAtZero: true,
            border: { display: false },
            grid: { color: p.grid },
            ticks: { callback: function (v) { return money(v, true); }, maxTicksLimit: 6 }
        }, extra || {});
    }

    var plainAxis = { grid: { display: false }, border: { display: false } };

    function tooltipMoney() {
        return {
            callbacks: {
                label: function (ctx) {
                    var v = ctx.parsed.y !== undefined && ctx.chart.options.indexAxis !== "y" ? ctx.parsed.y : ctx.parsed.x;
                    return " " + (ctx.dataset.label ? ctx.dataset.label + ": " : "") + money(v);
                }
            }
        };
    }

    function barDataset(label, data, color, p) {
        return {
            label: label,
            data: data,
            backgroundColor: color,
            borderColor: p.surface,
            borderWidth: { left: 1, right: 1 },
            borderRadius: 4,
            borderSkipped: "start",
            maxBarThickness: 28
        };
    }

    function make(id, config) {
        var canvas = document.getElementById(id);
        if (!canvas) return;
        if (charts[id]) charts[id].destroy();
        charts[id] = new Chart(canvas, config);
    }

    function readData() {
        var el = document.getElementById("chart-data");
        if (!el) return null;
        try { return JSON.parse(el.textContent); } catch (e) { return null; }
    }

    function renderPage() {
        var data = readData();
        var p = palette();
        applyDefaults(p);
        if (!data) return;

        if (data.pace) {
            var pace = data.pace;
            var datasets = [
                { label: "This month", data: pace.this_month, borderColor: p.s1, backgroundColor: p.s1,
                  borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25 },
                { label: "Last month", data: pace.last_month, borderColor: p.muted, backgroundColor: p.muted,
                  borderWidth: 2, borderDash: [4, 4], pointRadius: 0, pointHoverRadius: 4, tension: 0.25 }
            ];
            if (pace.budget) {
                datasets.push({ label: "Budget", data: pace.labels.map(function () { return pace.budget; }),
                    borderColor: p.critical, backgroundColor: p.critical, borderWidth: 1.5, borderDash: [2, 3],
                    pointRadius: 0, pointHoverRadius: 0 });
            }
            make("pace-chart", {
                type: "line",
                data: { labels: pace.labels, datasets: datasets },
                options: {
                    interaction: { mode: "index", intersect: false },
                    plugins: { tooltip: Object.assign(tooltipMoney(), {
                        callbacks: Object.assign(tooltipMoney().callbacks, {
                            title: function (items) { return "Day " + items[0].label; }
                        })
                    }) },
                    scales: { x: Object.assign({}, plainAxis, { ticks: { maxTicksLimit: 8 } }), y: moneyAxis(p) }
                }
            });
        }

        var monthly = data.trend || data.monthly;
        if (monthly) {
            make(data.trend ? "trend-chart" : "monthly-chart", {
                type: "bar",
                data: {
                    labels: monthly.labels,
                    datasets: [barDataset("Income", monthly.income, p.s1, p), barDataset("Expenses", monthly.expense, p.s2, p)]
                },
                options: {
                    interaction: { mode: "index", intersect: false },
                    plugins: { tooltip: tooltipMoney() },
                    scales: { x: plainAxis, y: moneyAxis(p) }
                }
            });
        }

        if (data.categories) {
            make("category-chart", {
                type: "bar",
                data: { labels: data.categories.labels, datasets: [barDataset("", data.categories.values, p.accent, p)] },
                options: {
                    indexAxis: "y",
                    plugins: { legend: { display: false }, tooltip: tooltipMoney() },
                    scales: { x: moneyAxis(p), y: Object.assign({}, plainAxis, { ticks: { color: p.ink } }) }
                }
            });
        }

        if (data.weekdays) {
            make("weekday-chart", {
                type: "bar",
                data: { labels: data.weekdays.labels, datasets: [barDataset("Avg per day", data.weekdays.values, p.accent, p)] },
                options: {
                    plugins: { legend: { display: false }, tooltip: tooltipMoney() },
                    scales: { x: plainAxis, y: moneyAxis(p) }
                }
            });
        }
    }

    // Calculators call this with yearly projections (values in currency units).
    var lastSavings = null;
    function renderSavings(rows) {
        lastSavings = rows;
        var p = palette();
        applyDefaults(p);
        make("savings-chart", {
            type: "bar",
            data: {
                labels: rows.map(function (r) { return "Yr " + r.year; }),
                datasets: [
                    Object.assign(barDataset("Contributions", rows.map(function (r) { return r.contributed * 100; }), p.s1, p), { stack: "s" }),
                    Object.assign(barDataset("Returns", rows.map(function (r) { return r.growth * 100; }), p.s2, p), { stack: "s", borderSkipped: false })
                ]
            },
            options: {
                interaction: { mode: "index", intersect: false },
                plugins: { tooltip: tooltipMoney() },
                scales: { x: Object.assign({}, plainAxis, { stacked: true }), y: moneyAxis(p, { stacked: true }) }
            }
        });
    }

    window.SpendlyCharts = { renderSavings: renderSavings, money: money };

    renderPage();
    document.addEventListener("spendly:themechange", function () {
        // Wait a frame so the new CSS variables are applied before reading them.
        requestAnimationFrame(function () {
            renderPage();
            if (lastSavings) renderSavings(lastSavings);
        });
    });
})();
