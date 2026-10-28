# Website Doctor

`web/doctor.html` is the upload, diagnosis and Markdown instructions page. Local checks
run in the browser. `web/assets/doctor-core.js` shares redaction, diagnosis,
allowed repair actions and evidence validation with the server.

On-device rules cover heap/native memory, Java class versions and architecture,
JVM flags, duplicate mods, required dependency versions and conflicts, Fabric
entrypoints/mixins, Forge/NeoForge failure sections, missing classes/methods,
corrupt archives, config syntax, file access/locks, connection/certificate
errors, sessions, graphics contexts, stack overflow and native crashes.
Specific underlying errors take priority over generic loading wrappers. Mod
targets come from explicit loader ownership or the report's suspected-mod
section; class packages, mixin filename prefixes and loaded-mod tables never
establish ownership. Uncertain attribution stays a reversible test, with
instructions to restore the mod if the same failure remains.
Missing dependencies are repaired rather than treated as mods to disable;
Minecraft/Java/loader requirements are not offered as downloadable mods.
Guides include up to four dependency conflicts and six steps; longer reports
are checked again after the first changes. Diagnostic lines and evidence are
bounded, and informational/optional dependency warnings do not trigger fixes.

`POST /api/doctor` runs `web/api/doctor.js` as a Vercel Node function. The root
`api/doctor.js` entry supports projects whose root directory is the repository;
projects rooted at `web/` discover the handler directly. Both Vercel configs set
a 60-second function budget. A plain static server supports local checks only.

Set **GROQ_API_KEY** and **KILO_API_KEY** as server environment secrets in the Vercel project for
each intended environment. For local Vercel development, use an ignored `.env`
or `.env.local` in the project root (`web/.env.example` shows the variable).
Run `vercel dev` with `web/` as the local project root. Do not copy a key into
HTML, browser JavaScript, a public environment variable or committed source.
Publishing requires separate authorization.

The server tries Groq first at `https://api.groq.com/openai/v1/chat/completions`.
Each analysis uses `crypto.randomInt` to select uniformly from
`openai/gpt-oss-120b`, `openai/gpt-oss-20b`, and `qwen/qwen3.8-27b`.
The Groq attempt has a 15-second limit. Any failure, including invalid output,
authentication, quota or a missing model, advances to Kilo's **`kilo-auto/free`**
router at `https://ai-gateway.kilo.ai/api/v1/chat/completions`.
Kilo gets up to two attempts, bounded to 45 seconds each and the remaining
shared 52-second budget. Terminal Kilo authentication/request/quota errors stop
its retry. Missing Groq configuration skips directly to Kilo; Groq alone can
also serve a request, but both secrets are needed for the complete fallback.
The application never accepts a client-selected provider, model or prompt.
Both providers use the same evidence and safe-instruction validator. The
client preserves the actual selected provider/model. It retains its local guide on failure and can cancel
the request. Provider computation may continue after a disconnected client.

The endpoint returns bounded failure codes distinguishing missing server
configuration, rejected credentials, unavailable credits/quota, rejected
requests, timeouts, invalid guides and upstream failures. It never returns the
provider's raw error text. The page explains those reasons while preserving
the on-device guide. An ignored local `.env` does not configure production:
set both provider secrets in the hosting project's Production environment and redeploy
for the new environment values and error messages to take effect.

Log bodies and model output are bounded; only supported guide actions and
matching evidence are accepted. Instructions render as an ordered list with
a limited Markdown subset (bold, inline code and paragraphs); raw HTML never renders.
Origin checks, **three analysis requests per rolling 30 minutes per address hash**,
and eight simultaneous requests per function instance limit repeated calls.
Provider fallback attempts count within one analysis. Denied requests do not
extend the window; visitor HTTP 429 responses include `scope: "visitor"`, bounded
`retry_after` seconds and an accurate `Retry-After` header. Capacity saturation
returns HTTP 503 `ai_busy` without consuming a visitor slot. The page distinguishes
visitor limits from upstream provider limits and retains the local guide.
The in-memory throttle is **not a global limit**: serverless instances and
restarts do not share it. Configure a shared hosting firewall rule or a durable
rate-limit store before relying on it as a site-wide quota. Visitors behind the
same address share this quota. The endpoint does not intentionally persist/log request bodies or
return provider error details. Free providers may retain/use prompts and output;
the page discloses this beside the upload area. File selection/drop starts AI;
pasting requires an Analyze click, and launcher handoffs remain local until that click.

The launcher transfers a redacted, zlib-compressed JSON excerpt in
`/doctor#report=<base64url>`. Version 1 has `log`, `version`, `reason`,
`original_chars` and `truncated`. The browser consumes/removes the fragment and
shows a local result without calling AI. Same-tab fragment changes are handled.
Transfers are capped at 7,500 URL characters for Windows browser wrappers;
file uploads accept .log/.txt up to 2 MB and preview a 64,000-character tail.
Email redaction uses bounded parts to avoid quadratic work on long log lines.

Verification:

```bash
.venv-build/bin/python tools/test_webdoctor.py
node tools/test_webdoctor_core.cjs
node tools/test_webdoctor_endpoint.cjs
python3 tools/test_webdoctor_browser.py
```

The browser check needs Playwright and installed Chromium; optionally set
`CUBEON_TEST_CHROMIUM`. It intercepts all network requests. Captures go under
`archive/ui-captures/`. The launcher suite invokes Node core and endpoint checks.
An opt-in `node tools/test_webdoctor_live.cjs` loads the local `.env` and sends
one synthetic memory error through the actual handler, without printing
credentials or using personal logs.
`node tools/test_webdoctor_live.cjs --groq-models` verifies each Groq model
without hiding failures behind Kilo. Live checks are opt-in and use synthetic logs.
