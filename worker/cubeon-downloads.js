/**
 * Cubeon download proxy - Cloudflare Worker (free tier).
 *
 * The repository is PRIVATE, so GitHub answers every anonymous release-asset
 * request with an auth wall (and signed asset URLs minted from a logged-in
 * session expire within the hour). This Worker is the middle piece: it holds
 * one GitHub token as a secret and streams the latest release's installer
 * files straight to anyone, with no GitHub page and no expiry.
 *
 *   GET /windowsdownload  -> streams Cubeon-Windows-x64-Setup.exe
 *   GET /linuxdownload    -> streams Cubeon-x86_64.AppImage
 *   GET /linuxdeb         -> streams cubeon_1.0.0_amd64.deb
 *   GET /linuxsetup       -> streams Cubeon-Linux-x86_64-Setup.sh
 *   GET /health           -> plain-text OK, for debugging by hand
 *
 * Bindings required: a secret GITHUB_TOKEN with read access to the repo
 * (read-only is enough):
 *
 *   npx wrangler deploy -c wrangler-downloads.toml
 *   echo "<token>" | npx wrangler secret put GITHUB_TOKEN -c wrangler-downloads.toml
 *
 * Quota: every request costs ONE GitHub API call to resolve the latest
 * release (5000/hour on a token) - the asset bytes themselves come off
 * GitHub's CDN and never pass through the API. The vercel.json routes point
 * at this Worker, so the token never reaches a browser.
 */

const REPOSITORY = "Shadow-457/Cubeon";

// Routes -> release asset names. Keep in sync with the ROUTES list in
// web/assets/site.js (which counts presses) and web/vercel.json.
const FILES = {
  "/windowsdownload": "Cubeon-Windows-x64-Setup.exe",
  "/linuxdownload": "Cubeon-x86_64.AppImage",
  "/linuxdeb": "cubeon_1.0.0_amd64.deb",
  "/linuxsetup": "Cubeon-Linux-x86_64-Setup.sh",
};

const jsonHeaders = {
  "User-Agent": "cubeon-downloads",
  "Accept": "application/vnd.github+json",
};

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return new Response("cubeon-downloads ok");
    }

    const assetName = FILES[url.pathname];
    if (!assetName || request.method !== "GET") {
      return new Response("not found", { status: 404 });
    }
    if (!env.GITHUB_TOKEN) {
      return new Response("server misconfigured: no GITHUB_TOKEN", { status: 500 });
    }

    // The asset lookup is the only metered call (5000/hour); bytes stream
    // from the CDN afterwards.
    const release = await fetch(
      `https://api.github.com/repos/${REPOSITORY}/releases/latest`,
      { headers: { ...jsonHeaders, Authorization: `Bearer ${env.GITHUB_TOKEN}` } }
    );
    if (!release.ok) {
      return new Response("release unavailable", { status: 502 });
    }
    const data = await release.json();
    const asset = (Array.isArray(data.assets) ? data.assets : [])
      .find((asset) => asset && asset.name === assetName);
    if (!asset) {
      return new Response(`no asset named ${assetName} in the latest release`, { status: 404 });
    }

    // Accept: application/octet-stream makes GitHub answer the asset with a
    // redirect to the real bytes; follow it and stream them on.
    const file = await fetch(asset.url, {
      headers: {
        "User-Agent": "cubeon-downloads",
        "Accept": "application/octet-stream",
        "Authorization": `Bearer ${env.GITHUB_TOKEN}`,
      },
      redirect: "follow",
    });
    if (!file.ok || !file.body) {
      return new Response("asset unavailable", { status: 502 });
    }

    return new Response(file.body, {
      headers: {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": `attachment; filename="${assetName}"`,
        "Content-Length": String(asset.size),
        "Cache-Control": "no-store",
      },
    });
  },
};
