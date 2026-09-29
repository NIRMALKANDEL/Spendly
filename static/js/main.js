(function () {
    "use strict";

    var root = document.documentElement;

    function $(sel, ctx) { return (ctx || document).querySelector(sel); }
    function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }

    function csrfToken() {
        var meta = $('meta[name="csrf-token"]');
        return meta ? meta.getAttribute("content") : "";
    }

    function announceThemeChange() {
        document.dispatchEvent(new CustomEvent("spendly:themechange"));
    }

    // ---------------------------------------------------------------- //
    // Mobile navigation drawer                                          //
    // ---------------------------------------------------------------- //
    var sidebar = $("[data-sidebar]");
    var scrim = $(".sidebar-scrim");
    var toggle = $("[data-nav-toggle]");

    function setNav(open) {
        if (!sidebar) return;
        sidebar.classList.toggle("open", open);
        if (scrim) scrim.hidden = !open;
        if (toggle) toggle.setAttribute("aria-expanded", String(open));
        document.body.classList.toggle("nav-open", open);
        if (open) {
            var first = $(".side-link", sidebar);
            if (first) first.focus();
        }
    }

    if (toggle) toggle.addEventListener("click", function () { setNav(true); });
    $$("[data-nav-close]").forEach(function (el) {
        el.addEventListener("click", function () { setNav(false); });
    });
    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && sidebar && sidebar.classList.contains("open")) {
            setNav(false);
            if (toggle) toggle.focus();
        }
    });

    // ---------------------------------------------------------------- //
    // Light / dark toggle                                               //
    // ---------------------------------------------------------------- //
    function effectiveMode() {
        var mode = root.getAttribute("data-mode");
        if (mode === "light" || mode === "dark") return mode;
        return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    $$("[data-mode-toggle]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var next = effectiveMode() === "dark" ? "light" : "dark";
            root.setAttribute("data-mode", next);
            announceThemeChange();
            if (root.hasAttribute("data-user-mode")) {
                fetch("/settings/mode", {
                    method: "POST",
                    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
                    body: JSON.stringify({ mode: next }),
                    credentials: "same-origin"
                }).catch(function () { /* preference just won't persist */ });
                var radio = $('input[name="mode"][value="' + next + '"]');
                if (radio) radio.checked = true;
            } else {
                try { localStorage.setItem("spendly-mode", next); } catch (e) { /* ignore */ }
            }
        });
    });

    window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", announceThemeChange);

    // ---------------------------------------------------------------- //
    // Appearance settings: live preview                                 //
    // ---------------------------------------------------------------- //
    var themeForm = $("[data-theme-form]");
    if (themeForm) {
        var accentToggle = $("[data-accent-toggle]", themeForm);
        var accentInput = $("[data-accent-input]", themeForm);

        var applyPreview = function () {
            var theme = $('input[name="theme"]:checked', themeForm);
            var mode = $('input[name="mode"]:checked', themeForm);
            if (theme) root.setAttribute("data-theme", theme.value);
            if (mode) root.setAttribute("data-mode", mode.value);
            if (accentToggle && accentToggle.checked && accentInput) {
                root.style.setProperty("--accent", accentInput.value);
            } else {
                root.style.removeProperty("--accent");
            }
            announceThemeChange();
        };
        themeForm.addEventListener("change", applyPreview);
        if (accentInput) {
            accentInput.addEventListener("input", function () {
                if (accentToggle) accentToggle.checked = true;
                applyPreview();
            });
        }
    }

    // ---------------------------------------------------------------- //
    // Confirm destructive actions                                       //
    // ---------------------------------------------------------------- //
    $$("form[data-confirm]").forEach(function (form) {
        form.addEventListener("submit", function (e) {
            if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
        });
    });

    // ---------------------------------------------------------------- //
    // Flash messages                                                    //
    // ---------------------------------------------------------------- //
    $$("[data-flash]").forEach(function (flash) {
        var close = function () {
            flash.classList.add("leaving");
            setTimeout(function () { flash.remove(); }, 200);
        };
        var btn = $("[data-flash-close]", flash);
        if (btn) btn.addEventListener("click", close);
        if (!flash.classList.contains("flash-error") && !flash.hasAttribute("data-sticky")) setTimeout(close, 6000);
    });

    // ---------------------------------------------------------------- //
    // Password fields                                                   //
    // ---------------------------------------------------------------- //
    $$("[data-password-toggle]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var input = btn.parentElement.querySelector("input");
            var show = input.type === "password";
            input.type = show ? "text" : "password";
            btn.textContent = show ? "Hide" : "Show";
            btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
        });
    });

    var strengthInput = $("[data-strength-input]");
    var strength = $("[data-strength]");
    if (strengthInput && strength) {
        strengthInput.addEventListener("input", function () {
            var v = strengthInput.value;
            var score = 0;
            if (v.length >= 8) score++;
            if (v.length >= 12) score++;
            if (/[a-z]/i.test(v) && /\d/.test(v)) score++;
            if (/[^a-z0-9]/i.test(v)) score++;
            strength.setAttribute("data-score", v ? String(score) : "");
            strength.setAttribute("aria-label", ["Weak", "Weak", "Fair", "Good", "Strong"][score] + " password");
        });
    }

    // ---------------------------------------------------------------- //
    // Transaction forms: categories follow the expense/income switch    //
    // ---------------------------------------------------------------- //
    $$("[data-tx-form]").forEach(function (form) {
        var select = $('select[name="category"]', form);
        if (!select) return;
        var sync = function () {
            var checked = $('input[name="kind"]:checked', form);
            var kind = checked ? checked.value : "expense";
            $$("optgroup", select).forEach(function (group) {
                var on = group.getAttribute("data-kind") === kind;
                group.disabled = !on;
                group.hidden = !on;
            });
            var current = select.options[select.selectedIndex];
            if (!current || current.parentElement.disabled) {
                var first = $('optgroup[data-kind="' + kind + '"] option', select);
                if (first) first.selected = true;
            }
        };
        $$('input[name="kind"]', form).forEach(function (r) { r.addEventListener("change", sync); });
        sync();
    });

    // ---------------------------------------------------------------- //
    // Chart <-> table toggles                                           //
    // ---------------------------------------------------------------- //
    $$("[data-table-toggle]").forEach(function (btn) {
        btn.addEventListener("click", function () {
            var table = document.getElementById(btn.getAttribute("data-table-toggle"));
            if (!table) return;
            table.hidden = !table.hidden;
            btn.textContent = table.hidden ? "Show table" : "Hide table";
        });
    });

    // ---------------------------------------------------------------- //
    // Receipt preview on the review form                                //
    // ---------------------------------------------------------------- //
    var receiptThumb = $("[data-receipt-preview]");
    if (receiptThumb) {
        try {
            var saved = sessionStorage.getItem("spendly-receipt-preview");
            if (saved && saved.indexOf("data:image/") === 0) { receiptThumb.src = saved; receiptThumb.hidden = false; }
        } catch (e) { /* ignore */ }
    }

    // ---------------------------------------------------------------- //
    // Service worker: makes Spendly installable and a share target      //
    // ---------------------------------------------------------------- //
    if ("serviceWorker" in navigator && window.isSecureContext) {
        window.addEventListener("load", function () {
            navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () { /* optional */ });
        });
    }

    // ---------------------------------------------------------------- //
    // "Install app" buttons                                             //
    // ---------------------------------------------------------------- //
    // Chrome fires beforeinstallprompt when the site is installable; we keep the
    // event and show our own buttons, so nobody has to hunt through browser menus.
    var installPrompt = null;
    var installButtons = $$("[data-install-app], [data-install-app-now]");
    var installReady = $("[data-install-ready]");
    var installHelp = $("[data-install-help]");
    var installedNote = $("[data-install-installed]");
    var standalone = window.matchMedia("(display-mode: standalone)").matches || window.navigator.standalone === true;

    function renderInstallState() {
        $$("[data-install-app]").forEach(function (b) { b.hidden = !installPrompt; });
        if (installReady) installReady.hidden = !installPrompt;
        if (installHelp) installHelp.hidden = !!installPrompt || standalone;
        if (installedNote) installedNote.hidden = !standalone;
    }

    window.addEventListener("beforeinstallprompt", function (e) {
        e.preventDefault();
        installPrompt = e;
        renderInstallState();
    });
    window.addEventListener("appinstalled", function () {
        installPrompt = null;
        renderInstallState();
    });
    installButtons.forEach(function (btn) {
        btn.addEventListener("click", function () {
            if (!installPrompt) {
                window.location.href = "/settings/#install";
                return;
            }
            installPrompt.prompt();
            installPrompt.userChoice.finally(function () { installPrompt = null; renderInstallState(); });
        });
    });
    renderInstallState();

    // ---------------------------------------------------------------- //
    // Quick add: live preview of what will be saved                     //
    // ---------------------------------------------------------------- //
    $$("[data-quick-add]").forEach(function (form) {
        var input = $("[data-quick-input]", form);
        var preview = $("[data-quick-preview]", form);
        var hint = preview.textContent;
        var timer = null, seq = 0;

        function show(data) {
            preview.classList.toggle("quick-error", !data.ok);
            if (!data.ok) { preview.textContent = data.error; return; }
            var when = data.when || data.date;
            preview.textContent = (data.kind === "income" ? "Income " : "Expense ") + data.amount + " · " + data.category +
                (data.description ? " · " + data.description : "") + " · " + when + "  ↵ to save";
        }

        input.addEventListener("input", function () {
            clearTimeout(timer);
            var q = input.value.trim();
            if (!q) { preview.textContent = hint; preview.classList.remove("quick-error"); return; }
            timer = setTimeout(function () {
                var mine = ++seq;
                fetch("/transactions/quick/preview?q=" + encodeURIComponent(q), { credentials: "same-origin" })
                    .then(function (r) { return r.json(); })
                    .then(function (data) { if (mine === seq) show(data); })
                    .catch(function () { /* preview is optional */ });
            }, 200);
        });
    });
})();
