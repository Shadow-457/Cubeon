/* GitHub Release asset download totals for the public Cubeon site.
 *
 * The site itself never receives a GitHub credential. On a private repo,
 * configure GITHUB_TOKEN in Vercel with read-only Contents permission; on a
 * public repo the endpoint also works without it. Results are cached at the
 * Vercel edge for 15 minutes so page views do not burn GitHub API quota.
 */
const REPOSITORY = "Shadow-457/Cubeon";
const DOWNLOAD_ASSETS = new Set([
  "Cubeon-x86_64.AppImage",
  "cubeon_1.0.0_amd64.deb",
  "Cubeon-Linux-x86_64-Setup.sh",
  "Cubeon-Windows-x64-Setup.exe",
]);

module.exports = async function downloadCount(req, res) {
  if (req.method !== "GET") {
    res.setHeader("Allow", "GET");
    return res.status(405).json({ error: "method_not_allowed" });
  }

  const headers = {
    Accept: "application/vnd.github+json",
    "User-Agent": "cubeon-download-counter",
  };
  const token = process.env.GITHUB_TOKEN || process.env.GH_TOKEN;
  if (token) headers.Authorization = `Bearer ${token}`;

  try {
    const response = await fetch(
      `https://api.github.com/repos/${REPOSITORY}/releases/latest`,
      { headers }
    );
    if (!response.ok) {
      return res.status(response.status).json({ error: "release_unavailable" });
    }
    const release = await response.json();
    const assets = Array.isArray(release.assets) ? release.assets : [];
    const counts = {};
    let total = 0;
    for (const asset of assets) {
      // The payload is third-party JSON: an entry can be null and a counter can
      // be missing or nonsense. Neither may turn a page view into a 503 - the
      // null entry did exactly that before this guard existed.
      if (!asset || typeof asset !== "object") continue;
      if (!DOWNLOAD_ASSETS.has(asset.name)) continue;
      const raw = asset.download_count;
      // Same rule as _download_count() in tools/refresh_download_count.py:
      // whole, non-negative numbers only - "many", -4, true or 2.5 all mean 0.
      const count = (typeof raw === "number" && Number.isInteger(raw) && raw > 0) ? raw : 0;
      counts[asset.name] = count;
      total += count;
    }
    res.setHeader("Cache-Control", "public, s-maxage=900, stale-while-revalidate=3600");
    return res.status(200).json({ total, assets: counts });
  } catch (_) {
    return res.status(503).json({ error: "release_unavailable" });
  }
};
