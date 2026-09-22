# 2026-09-22 — release download counter

The web root now contains `api/download-count.js`, a Vercel function that sums
the current release's installer asset `download_count` values and is cached for
15 minutes. `web/assets/site.js` displays it on home and download pages only
when the endpoint succeeds; private repositories need a read-only
`GITHUB_TOKEN` (or `GH_TOKEN`) set in Vercel. Verified with Node syntax checks.
