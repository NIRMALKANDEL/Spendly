// Receipt scanning: resize the image, read it on the device with Tesseract.js
// (or hand it to the server's AI reader when that's enabled), then post the
// result to /receipts/review, which shows the pre-filled transaction form.
(function () {
    "use strict";

    var root = document.querySelector("[data-scanner]");
    if (!root) return;

    var form = document.querySelector("[data-review-form]");
    var preview = root.querySelector("[data-preview]");
    var prompt = root.querySelector("[data-drop-prompt]");
    var drop = root.querySelector("[data-drop]");
    var statusBox = root.querySelector("[data-status]");
    var statusText = root.querySelector("[data-status-text]");
    var progressBar = root.querySelector("[data-progress]");
    var errorBox = root.querySelector("[data-scan-error]");
    var useAI = root.getAttribute("data-ai") === "1";
    var busy = false;

    var PREVIEW_KEY = "spendly-receipt-preview";
    // Tesseract skips very large glyphs (the big "₹349" headline) and misreads
    // tiny ones, so the image is read at two widths and the texts combined.
    // Measured on UPI screenshots: plain colour pixels beat grayscale/threshold
    // pre-processing, and sparse-text mode (PSM 11) keeps amounts on their own line.
    var OCR_WIDTHS = [1000, 500];
    var MAX_SIDE = 2600;

    function setStatus(text, fraction) {
        statusBox.hidden = false;
        statusText.textContent = text;
        if (typeof fraction === "number") progressBar.style.width = Math.round(fraction * 100) + "%";
    }

    function showError(message) {
        busy = false;
        statusBox.hidden = true;
        errorBox.textContent = message;
        errorBox.hidden = false;
        var paste = document.querySelector(".paste-card");
        if (paste) paste.open = true;
    }

    function loadImage(src) {
        return new Promise(function (resolve, reject) {
            var img = new Image();
            img.onload = function () { resolve(img); };
            img.onerror = function () { reject(new Error("That file isn't an image we can open.")); };
            img.src = src;
        });
    }

    function readFile(file) {
        return new Promise(function (resolve, reject) {
            var reader = new FileReader();
            reader.onload = function () { resolve(reader.result); };
            reader.onerror = function () { reject(new Error("Couldn't read that file.")); };
            reader.readAsDataURL(file);
        });
    }

    function drawScaled(img, targetWidth, maxSide) {
        var scale = Math.min(targetWidth / img.naturalWidth, maxSide / Math.max(img.naturalWidth, img.naturalHeight));
        if (!isFinite(scale) || scale <= 0) scale = 1;
        var canvas = document.createElement("canvas");
        canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
        canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
        var ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        return canvas;
    }

    function rememberPreview(img) {
        try {
            var small = drawScaled(img, 480, 900);
            sessionStorage.setItem(PREVIEW_KEY, small.toDataURL("image/jpeg", 0.7));
        } catch (e) { /* preview is a nicety */ }
    }

    function submitText(text) {
        form.elements.mode.value = "ocr";
        form.elements.text.value = text;
        setStatus("Opening the draft…", 1);
        form.submit();
    }

    function submitImageForAI(canvas) {
        return new Promise(function (resolve, reject) {
            if (typeof DataTransfer === "undefined") return reject(new Error("no DataTransfer"));
            canvas.toBlob(function (blob) {
                try {
                    var transfer = new DataTransfer();
                    transfer.items.add(new File([blob], "receipt.jpg", { type: "image/jpeg" }));
                    form.elements.image.files = transfer.files;
                    form.elements.mode.value = "ai";
                    setStatus("Reading receipt with AI…", 0.6);
                    form.submit();
                    resolve();
                } catch (e) { reject(e); }
            }, "image/jpeg", 0.85);
        });
    }

    function ocr(canvases) {
        if (!window.Tesseract) return Promise.reject(new Error("The text reader didn't load. Check your connection and reload."));
        var stages = { "loading tesseract core": 0.05, "initializing tesseract": 0.1, "loading language traineddata": 0.15,
                       "initializing api": 0.25, "recognizing text": 0.3 };
        return Tesseract.createWorker("eng", 1, {
            workerPath: root.getAttribute("data-worker-path"),
            corePath: root.getAttribute("data-core-path"),
            langPath: root.getAttribute("data-lang-path"),
            workerBlobURL: false,
            gzip: true,
            logger: function (m) {
                var base = stages[m.status];
                if (base === undefined) return;
                if (m.status === "recognizing text") return;  // per-pass status is set below
                var label = m.status === "loading language traineddata" ? "Downloading reader (first time only)…" : "Starting reader…";
                setStatus(label, base + 0.05 * (m.progress || 0));
            }
        }).then(function (worker) {
            var texts = [];
            var finish = function (value) { worker.terminate(); return value; };
            var chain = worker.setParameters({ tessedit_pageseg_mode: "11" });
            canvases.forEach(function (canvas, index) {
                chain = chain.then(function () {
                    setStatus(index ? "Double-checking…" : "Reading receipt…", 0.3 + 0.35 * index);
                    return worker.recognize(canvas);
                }).then(function (result) { texts.push(result.data.text || ""); });
            });
            return chain.then(function () { return finish(texts.join("\n")); },
                              function (err) { finish(); throw err; });
        });
    }

    function processImageSource(src) {
        if (busy) return;
        busy = true;
        errorBox.hidden = true;
        setStatus("Preparing image…", 0.02);
        return loadImage(src).then(function (img) {
            preview.src = src;
            preview.hidden = false;
            prompt.hidden = true;
            rememberPreview(img);
            if (useAI) {
                return submitImageForAI(drawScaled(img, Math.min(img.naturalWidth, 1600), 1600))
                    .catch(function () { return runOcr(img); });
            }
            return runOcr(img);
        }).catch(function (err) {
            showError((err && err.message) || "Something went wrong reading that image.");
        });
    }

    function runOcr(img) {
        var canvases = OCR_WIDTHS.map(function (width) { return drawScaled(img, width, MAX_SIDE); });
        return ocr(canvases).then(function (text) {
            if (!text.trim()) throw new Error("No text found in that image. Try a sharper screenshot, or paste the text below.");
            submitText(text);
        });
    }

    function handleFile(file) {
        if (!file) return;
        if (!/^image\//.test(file.type)) return showError("Please choose an image (JPG, PNG or WebP).");
        if (file.size > 15 * 1024 * 1024) return showError("That image is over 15 MB. Try a screenshot instead.");
        readFile(file).then(processImageSource, function (e) { showError(e.message); });
    }

    Array.prototype.forEach.call(root.querySelectorAll("[data-file-input]"), function (input) {
        input.addEventListener("change", function () { handleFile(input.files && input.files[0]); input.value = ""; });
    });

    ["dragenter", "dragover"].forEach(function (type) {
        drop.addEventListener(type, function (e) { e.preventDefault(); drop.classList.add("dragging"); });
    });
    ["dragleave", "drop"].forEach(function (type) {
        drop.addEventListener(type, function (e) { e.preventDefault(); drop.classList.remove("dragging"); });
    });
    drop.addEventListener("drop", function (e) { handleFile(e.dataTransfer.files && e.dataTransfer.files[0]); });

    // Paste an image straight from the clipboard (desktop).
    document.addEventListener("paste", function (e) {
        var items = (e.clipboardData && e.clipboardData.items) || [];
        for (var i = 0; i < items.length; i++) {
            if (items[i].type.indexOf("image/") === 0) { handleFile(items[i].getAsFile()); e.preventDefault(); return; }
        }
    });

    // ---------------------------------------------------------------- //
    // Shared from another app                                           //
    // ---------------------------------------------------------------- //
    function sharedTextFromPage() {
        var el = document.getElementById("shared-text");
        try { return el ? JSON.parse(el.textContent) : ""; } catch (e) { return ""; }
    }

    function start() {
        try { sessionStorage.removeItem(PREVIEW_KEY); } catch (e) { /* ignore */ }

        // 1. Server-side fallback rendered the shared image into the page.
        var embedded = document.querySelector("[data-shared-image]");
        if (embedded) return processImageSource(embedded.getAttribute("src"));
        var pageText = sharedTextFromPage();

        // 2. The service worker stashed the share in the cache.
        var params = new URLSearchParams(location.search);
        if (params.get("shared") === "error") return showError("That share couldn't be read. Try choosing the screenshot instead.");
        if (params.get("shared") === "1" && "caches" in window) {
            return caches.open("spendly-share").then(function (cache) {
                return Promise.all([cache.match("/receipts/shared-file"), cache.match("/receipts/shared-text")])
                    .then(function (hits) {
                        cache.delete("/receipts/shared-file");
                        cache.delete("/receipts/shared-text");
                        var file = hits[0], text = hits[1];
                        if (file) return file.blob().then(function (blob) { handleFile(new File([blob], "shared", { type: blob.type || "image/png" })); });
                        if (text) return text.text().then(function (t) { if (t.trim()) submitText(t); });
                        showError("Nothing was shared. Choose the screenshot below instead.");
                    });
            });
        }
        if (pageText && pageText.trim()) {
            form.elements.mode.value = "text";
            form.elements.text.value = pageText;
            form.submit();
        }
    }

    start();
})();
