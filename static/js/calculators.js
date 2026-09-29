// Client-side mirrors of services/finance.py (kept in sync by tests on the Python side).
(function () {
    "use strict";

    var body = document.body;
    var locale = body.getAttribute("data-grouping") === "indian" ? "en-IN" : "en-US";

    function fmt(value, symbol) {
        if (!isFinite(value)) return "—";
        return symbol + new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(Math.round(value));
    }

    function monthlyRate(annual) { return annual / 100 / 12; }

    function futureValue(principal, monthly, annual, months) {
        var r = monthlyRate(annual);
        if (r === 0) return principal + monthly * months;
        var g = Math.pow(1 + r, months);
        return principal * g + monthly * (g - 1) / r;
    }

    function requiredMonthly(target, current, annual, months) {
        if (months <= 0) return Math.max(target - current, 0);
        var r = monthlyRate(annual);
        var needed;
        if (r === 0) {
            needed = (target - current) / months;
        } else {
            var g = Math.pow(1 + r, months);
            needed = (target - current * g) * r / (g - 1);
        }
        return Math.max(needed, 0);
    }

    function monthsToGoal(target, current, monthly, annual) {
        if (current >= target) return 0;
        var r = monthlyRate(annual);
        if (r === 0) return monthly > 0 ? Math.ceil((target - current) / monthly) : null;
        if (monthly <= 0 && current <= 0) return null;
        var den = current * r + monthly;
        if (den <= 0) return null;
        var n = Math.ceil(Math.log((target * r + monthly) / den) / Math.log(1 + r) - 1e-9);
        return n <= 1200 ? n : null;
    }

    function emi(principal, annual, months) {
        var r = monthlyRate(annual);
        if (months <= 0) return NaN;
        if (r === 0) return principal / months;
        var g = Math.pow(1 + r, months);
        return principal * r * g / (g - 1);
    }

    function num(form, name) {
        var v = parseFloat(form.elements[name].value);
        return isFinite(v) && v >= 0 ? v : 0;
    }

    function out(section, key, text) {
        var el = section.querySelector('[data-out="' + key + '"]');
        if (el) el.textContent = text;
    }

    function duration(months) {
        var y = Math.floor(months / 12), m = months % 12;
        var parts = [];
        if (y) parts.push(y + (y === 1 ? " year" : " years"));
        if (m || !y) parts.push(m + (m === 1 ? " month" : " months"));
        return parts.join(" ");
    }

    var calculators = {
        savings: function (f, s, sym) {
            var principal = num(f, "principal"), monthly = num(f, "monthly"), rate = num(f, "rate");
            var years = Math.min(Math.max(Math.round(num(f, "years")), 1), 60);
            var fv = futureValue(principal, monthly, rate, years * 12);
            var contributed = principal + monthly * years * 12;
            out(s, "fv", fmt(fv, sym));
            out(s, "contrib", fmt(contributed, sym));
            out(s, "growth", fmt(fv - contributed, sym));
            var rows = [];
            for (var y = 1; y <= years; y++) {
                var value = futureValue(principal, monthly, rate, y * 12);
                var c = principal + monthly * y * 12;
                rows.push({ year: y, contributed: Math.round(c), growth: Math.round(value - c) });
            }
            if (window.SpendlyCharts) window.SpendlyCharts.renderSavings(rows);
        },
        goal: function (f, s, sym) {
            var target = num(f, "target"), current = num(f, "current"), rate = num(f, "rate");
            var months = Math.max(Math.round(num(f, "months")), 1);
            var monthly = requiredMonthly(target, current, rate, months);
            var total = monthly * months;
            out(s, "monthly", current >= target ? "Already there 🎉" : fmt(monthly, sym));
            out(s, "total", fmt(total, sym));
            out(s, "growth", fmt(Math.max(target - current - total, 0), sym));
        },
        time: function (f, s, sym) {
            var n = monthsToGoal(num(f, "target"), num(f, "current"), num(f, "monthly"), num(f, "rate"));
            if (n === null) {
                out(s, "duration", "Never at this rate");
                out(s, "date", "Increase your monthly saving");
                return;
            }
            out(s, "duration", n === 0 ? "Already there 🎉" : duration(n));
            var d = new Date();
            d.setMonth(d.getMonth() + n);
            out(s, "date", d.toLocaleDateString(undefined, { month: "long", year: "numeric" }));
        },
        emergency: function (f, s, sym) {
            var target = num(f, "expenses") * Math.round(num(f, "months"));
            out(s, "target", fmt(target, sym));
            out(s, "gap", fmt(Math.max(target - num(f, "current"), 0), sym));
        },
        loan: function (f, s, sym) {
            var principal = num(f, "principal"), months = Math.round(num(f, "months"));
            var payment = emi(principal, num(f, "rate"), months);
            out(s, "emi", fmt(payment, sym));
            out(s, "total", fmt(payment * months, sym));
            out(s, "interest", fmt(payment * months - principal, sym));
        }
    };

    Array.prototype.forEach.call(document.querySelectorAll("[data-calc]"), function (section) {
        var kind = section.getAttribute("data-calc");
        var form = section.querySelector("form");
        var sym = section.getAttribute("data-currency") || "₹";
        var run = function () { calculators[kind](form, section, sym); };
        form.addEventListener("input", run);
        form.addEventListener("submit", function (e) { e.preventDefault(); });
        run();
    });
})();
