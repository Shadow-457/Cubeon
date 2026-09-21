# 2026-09-21 — web downloads and clean routes

The site was linking to `../dist/...`, but the deployed web root does not
contain the ignored `dist/` directory, causing download 404s. It also exposed
HTML filenames through explicit `index.html`/`404.html` links. Download CTAs
now use clean routes (`/linuxdownload`, `/windowsdownload`, etc.) backed by
`web/_redirects` to GitHub Release assets; page navigation uses clean paths.
The CI release workflow now publishes the Debian package and Windows installer
assets that those routes target. `/404` is mapped to the custom not-found page.
