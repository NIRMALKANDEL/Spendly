// Spendly service worker.
//
// Its one job is the Android share target: when a payment app shares a
// receipt to Spendly, the OS POSTs it to /receipts/share. We keep the shared
// image/text in a private cache and open the scan page, which reads it on the
// device. The image never has to be uploaded. Every other request goes
// straight to the network (no offline caching of personal data).

const SHARE_CACHE = "spendly-share";

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
    const url = new URL(event.request.url);
    if (event.request.method === "POST" && url.origin === self.location.origin && url.pathname === "/receipts/share") {
        event.respondWith(handleShare(event.request));
    }
    // Anything else: no respondWith, so the browser fetches normally.
});

async function handleShare(request) {
    try {
        const form = await request.formData();
        const cache = await caches.open(SHARE_CACHE);
        await cache.delete("/receipts/shared-file");
        await cache.delete("/receipts/shared-text");

        const file = form.get("receipt");
        if (file && typeof file !== "string" && file.size) {
            await cache.put("/receipts/shared-file", new Response(file, { headers: { "Content-Type": file.type || "image/*" } }));
        }
        const text = ["title", "text", "url"].map((k) => form.get(k)).filter((v) => typeof v === "string" && v.trim()).join("\n");
        if (text) {
            await cache.put("/receipts/shared-text", new Response(text, { headers: { "Content-Type": "text/plain; charset=utf-8" } }));
        }
        return Response.redirect("/receipts/scan?shared=1", 303);
    } catch (err) {
        return Response.redirect("/receipts/scan?shared=error", 303);
    }
}
