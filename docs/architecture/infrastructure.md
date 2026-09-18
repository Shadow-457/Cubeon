# Architecture & Infrastructure - Current State vs. Production

> This document maps the current architecture and identifies the infrastructure gaps that must be closed to move from prototype to production.

---

## Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     CUBEON LAUNCHER                          │
│                    (Python + Flet)                            │
│                                                              │
│  main.py ─── ui/*.py (Flet widgets)                         │
│     │                                                        │
│     └── launcher_core.py ─── cubeon/*.py (business logic)    │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ launch.py│ │ mods.py  │ │ skins.py │ │server.py │       │
│  │ (Java)   │ │(Modrinth)│ │ (Worker) │ │ (Paper)  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
└──────────┬────────────────────────────────────┬──────────────┘
           │                                    │
           ▼                                    ▼
   minecraft-launcher-lib              Cloudflare Workers (free tier)
   (version manifests,                 ┌──────────────────────────┐
    command building)                   │ cubeon-skins.js          │
                                        │ cubeon-invites.js        │
                                        │ cubeon-friends.js (DO)   │
                                        └──────────────────────────┘
```

### Launcher (Desktop App)
- **Framework:** Flet 0.86 (Flutter-based Python UI)
- **Language:** Python 3.11
- **Entry:** `main.py` → Flet app with sidebar navigation
- **Business logic:** `cubeon/` package (no UI imports)
- **UI layer:** `ui/` package (Flet widgets, no business logic)
- **State:** JSON files in `~/.cubeon_launcher/`

### Backend (Cloudflare Workers)
- **cubeon-skins.js** - Skin upload, identity heartbeat, CSL profile lookups (KV-backed)
- **cubeon-invites.js** - Invite code generation/resolution (KV-backed)
- **cubeon-friends.js** - Realtime presence, chat, voice signalling (Durable Object)
- **Runtime:** Cloudflare Workers free tier
- **Storage:** KV (skins, invites) + Durable Object (friends)

### External APIs
- **Modrinth** - Mod/plugin search and download
- **PaperMC** - Server jar downloads
- **minecraft-launcher-lib** - Version manifests, command building, Java detection

---

## Infrastructure Gaps

### 1. No Backend Health Monitoring

**Current:** Workers are deployed manually via the Cloudflare dashboard. There is no health check, uptime monitoring, or alerting.

**Production need:**
- Add uptime monitoring (e.g., Cloudflare Workers Analytics, UptimeRobot, or a simple health-check ping)
- Add error-rate alerting on the Workers
- Log Worker invocations to a structured sink (Cloudflare Workers Analytics, or a logging service)

---

### 2. No CDN / Asset Distribution

**Current:** The launcher downloads mods and Paper jars directly from Modrinth/PaperMC on every install. There is no local caching of download manifests or partial downloads.

**Production need:**
- Implement HTTP Range (206) resume for large downloads
- Cache version manifests locally with TTL
- Consider a local proxy/mirror for frequently-downloaded assets (Fabric API, etc.)

---

### 3. No Rate Limiting or Abuse Protection

**Current:** The Worker endpoints have no rate limiting. The name-claim endpoint accepts unlimited requests. Skin uploads have no size limit beyond the Worker's body-size cap.

**Production need:**
- Add rate limiting per IP on the Workers (Cloudflare rate-limiting rules or Worker-level logic)
- Validate upload sizes server-side (skin PNGs are 64×64 or 64×32; anything larger is invalid)
- Add a simple abuse-report mechanism

---

### 4. No Data Retention / Cleanup Policy

**Current:** KV entries persist indefinitely. The Durable Object holds all friend data forever. Old skin uploads are never cleaned up.

**Production need:**
- Define retention policies (e.g., inactive accounts after 90 days, old skin uploads after 365 days)
- Implement TTL on KV entries where appropriate
- Add a "delete my data" / GDPR-style deletion endpoint

---

### 5. No Multi-Region / Redundancy

**Current:** All Workers are on a single Cloudflare account. If the account is suspended or the Workers are deleted, the entire backend goes down.

**Production need:**
- Document the single-point-of-failure risk
- Consider a backup/mirror Worker on a second account
- Implement graceful degradation in the launcher when Workers are unreachable (already partially done: Friends shows "offline" state, skin network falls back to local skin)

---

### 6. No Versioned API Contracts

**Current:** Client and server are deployed independently. There is no version header, no compatibility check, and no deprecation path. A Worker change can break any launcher version.

**Production need:**
- Add an `X-Client-Version` header to every request
- Add a `/api/version` endpoint that returns the minimum supported client version
- The launcher should check this on startup and warn if it's too old

---

### 7. No CI/CD for Workers

**Current:** Workers are pasted into the Cloudflare dashboard editor. No automated deployment, no staging environment, no rollback.

**Production need:**
- Add `wrangler deploy` to the CI pipeline (or a manual deploy script)
- Add a staging Worker (`cubeon-skins-staging`) for testing
- Tag Worker deployments with the commit SHA for traceability

---

### 8. No Structured Error Reporting

**Current:** Worker errors return plain JSON `{error: "..."}`. The launcher swallows most exceptions with `except Exception: pass`.

**Production need:**
- Standardize Worker error responses: `{error: {code: "NAME_TAKEN", message: "...", request_id: "..."}}`
- Add request-id tracking for debugging
- Surface request IDs in the launcher's diagnostic export

---

### 9. No Backup / Disaster Recovery for Backend Data

**Current:** If the Cloudflare account is lost, all skin uploads, invite codes, friend lists, and name registrations are gone with no recovery path.

**Production need:**
- Implement periodic KV export to a durable store (R2, S3, or a database)
- Document the recovery process if Workers are deleted
- Consider a self-hosted fallback for critical data (name registry)

---

### 10. No Performance Benchmarking

**Current:** No baseline measurements for:
- Download speed (mod installs, Paper jar)
- WebSocket connection time
- Launcher startup time
- Memory footprint under load

**Production need:**
- Add a startup-time profiler
- Benchmark download throughput
- Track WebSocket reconnection frequency
- Set performance budgets (e.g., "launcher must start in <3 seconds")

---

## Deployment Topology (Target State)

```
┌──────────────────────────────────────────────────────────────────┐
│                     CUBEON LAUNCHER (Desktop)                     │
│                                                                   │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │  UI (Flet)   │  │  Business   │  │  Observability          │  │
│  │              │  │  Logic      │  │  • Structured logging   │  │
│  │  • Play tab  │  │  • launch   │  │  • Crash reporting      │  │
│  │  • Mods tab  │  │  • mods     │  │  • Performance metrics  │  │
│  │  • Skin tab  │  │  • skins    │  │  • Diagnostic export    │  │
│  │  • Friends   │  │  • friends  │  │                         │  │
│  │  • Server    │  │  • server   │  │                         │  │
│  │  • Settings  │  │  • config   │  │                         │  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
└──────────┬───────────────────────────────┬───────────────────────┘
           │                               │
           ▼                               ▼
   ┌───────────────┐           ┌────────────────────────────┐
   │  External APIs │           │  Cloudflare Workers         │
   │               │           │  (versioned, monitored)     │
   │  • Modrinth   │           │                              │
   │  • PaperMC    │           │  ┌────────┐ ┌────────────┐  │
   │  • Mojang     │           │  │ skins  │ │  friends   │  │
   │               │           │  │ (KV)   │ │  (DO+KV)   │  │
   └───────────────┘           │  └────────┘ └────────────┘  │
                               │  ┌─────────┐                │
                               │  │ invites │                │
                               │  │ (KV)    │                │
                               │  └─────────┘                │
                               │                              │
                               │  Monitoring: Workers Analytics│
                               │  Deploy: wrangler (CI)       │
                               │  Staging: -staging namespace  │
                               └────────────────────────────┘
```

---

## Key Metrics to Track (Post-Launch)

| Metric | Target | Why |
|--------|--------|-----|
| Launcher cold-start time | < 3 seconds | First impression |
| Mod download speed | > 2 MB/s average | Install experience |
| WebSocket reconnect time | < 5 seconds | Friends availability |
| Worker error rate | < 0.1% | Backend reliability |
| Crash-free session rate | > 99% | Stability |
| Auto-update adoption (7 days) | > 50% | Security patching |
| Skin upload success rate | > 99% | Identity feature |

---

## Migration Path: Prototype → Production

1. **Week 1-2:** Add CI test job, structured logging, version check
2. **Week 3-4:** Add auto-update, Worker API docs, CHANGELOG
3. **Month 2:** Download resume, macOS build, rate limiting
4. **Month 3:** Crash reporting, performance benchmarking, accessibility audit
5. **Month 4+:** i18n, ARM64 builds, backup/DR for backend data
