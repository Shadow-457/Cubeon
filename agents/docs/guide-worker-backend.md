# The Backend - Cloudflare Workers

> How the three Cloudflare Workers power the skin network, invite codes, and friends system.

---

## Overview

```
┌─────────────────────────────────────────────────┐
│              Cloudflare Workers                   │
│                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────┐ │
│  │ cubeon-skins  │  │ cubeon-invites│  │ friends│ │
│  │   (KV)       │  │   (KV)       │  │  (DO)  │ │
│  └──────────────┘  └──────────────┘  └────────┘ │
└─────────────────────────────────────────────────┘
         ▲                   ▲              ▲
         │                   │              │
    HTTP POST/GET        HTTP PUT/GET    WebSocket
         │                   │              │
┌────────┴───────────────────┴──────────────┴────┐
│              Cubeon Launcher                     │
│  cubeon/skins.py    cubeon/invites.py   cubeon/friends.py │
└────────────────────────────────────────────────┘
```

All three workers run on Cloudflare's free tier. No VPS, no database costs. The trade-off: strict write limits (KV) and no persistent state across cold starts ( Workers).

---

## cubeon-skins.js - Skin Network

**Deployed at:** `https://cubeon-skins.hamza-457-shahbaz.workers.dev`

**Purpose:** Manages player identities and skins so other Cubeon players can see each other's skins on any server.

### KV Layout

| Key | Value | Purpose |
|-----|-------|---------|
| `pointer:<lowercase-name>` | `<uuid>` | Maps a username to its owning UUID |
| `skin:<uuid>` | `{"url": "...", "model": "default"/"slim"}` | The skin texture for a UUID |
| `owner:<uuid>` | SHA-256 of secret | TOFU ownership (first writer claims) |
| `texture:<sha256>` | base64 PNG | Content-addressed skin texture |
| `report:<uuid>` | `{"reason": "...", "ts": ...}` | Pending moderation report (30-day TTL) |
| `blocked:<uuid>` | any value | Moderation kill-switch |

### Endpoints

| Method | Path | Auth | What It Does |
|--------|------|------|-------------|
| POST | `/api/heartbeat` | Bearer secret | Claims UUID, points name at it |
| POST | `/api/skin` | Bearer secret | Uploads a composed skin sheet |
| POST | `/report` | None | Flags a skin for review |
| GET | `/skins/<name>.json` | None | CSL profile lookup (name → skin URL) |
| GET | `/textures/<id>` | None | Serves a texture by content hash |
| GET | `/health` | None | Plain-text "ok" |

### How Skin Resolution Works

When a player joins a server, every Cubeon user's CustomSkinLoader asks:

```
GET /skins/alex.json
```

The Worker:
1. Looks up `pointer:alex` → gets the UUID
2. Looks up `skin:<uuid>` → gets the texture URL
3. Returns a JSON profile: `{username, textures: {default: "...", cape: "..."}}`

CSL then fetches the texture from `/textures/<sha256>`.

### Write-Frugal Design

KV's free tier allows ~1,000 writes/day. The launcher avoids wasting them:

- **Heartbeat only fires when something changed** (username, UUID, or API base)
- **Skin upload only fires when the image hash changed**
- **Unchanged launches cost zero writes**
- The publish state is tracked client-side in `skin_net.json`

### Cape Delivery

Every Cubeon player gets the shared Cubeon cape automatically. It's served as a hardcoded base64 constant in the Worker (zero KV reads). The cape texture is content-addressed and cached immutably.

### Moderation

Reports are recorded with a 30-day TTL. A human sets `blocked:<uuid>` manually in the KV dashboard. Blocked players get 404 on all lookups - they fall back to vanilla Steve/Alex.

---

## cubeon-invites.js - Invite Codes

**Deployed at:** `https://cubeon-invites.hamza-457-shahbaz.workers.dev`

**Purpose:** Maps short codes (`CUBE-7F4K-9QMN`) to server addresses.

### KV Layout

| Key | Value | Purpose |
|-----|-------|---------|
| `code:<CUBE-XXXX-XXXX>` | `{"address": "...", "version": "...", "loader": "...", "owner_hash": "..."}` | Code → address mapping |

### Endpoints

| Method | Path | Auth | What It Does |
|--------|------|------|-------------|
| PUT | `/i/<code>` | Bearer secret | Creates or updates a code |
| GET | `/i/<code>` | None | Resolves a code to an address |
| DELETE | `/i/<code>` | Bearer secret | Takes a code offline |

### Code Lifecycle

1. **Mint:** Host generates code + secret, PUTs to `/i/CUBE-...` → code created
2. **Share:** Host sends code to friends
3. **Resolve:** Friend GETs `/i/CUBE-...` → gets server address
4. **Repoint:** Host PUTs again with new address (tunnel reassigned)
5. **Delete:** Host DELETEs when server stops

### Security

- Owner is verified by SHA-256 of the secret (same TOFU pattern as skins)
- Code format uses an unambiguous 25-character alphabet (no 0/O, 1/I/L, etc.)
- Codes are case-insensitive and punctuation-insensitive on input

---

## cubeon-friends.js - Friends System

**Deployed at:** `https://cubeon-friends.hamza-457-shahbaz.workers.dev`

**Purpose:** Realtime social layer - presence, chat, groups, voice signalling, P2P session coordination.

### Architecture

Unlike the other workers (stateless KV), this one uses a **Durable Object** (DO) - a single instance holding all WebSocket connections and a SQLite database.

**Why a DO?** KV's free tier allows ~1,000 writes/day. A 30-second presence heartbeat would exhaust that on its own. DOs have their own metered storage and can hold live connections.

### Database Schema (SQLite in the DO)

```sql
CREATE TABLE names (
    name TEXT PRIMARY KEY,      -- canonical lowercase
    display TEXT,               -- first-claimed casing
    secret_hash TEXT,           -- SHA-256 of owning secret
    uuid TEXT,                  -- player UUID
    blocked INTEGER DEFAULT 0,
    created INTEGER
);

CREATE TABLE friends (
    owner TEXT, friend TEXT,
    PRIMARY KEY (owner, friend)
);

CREATE TABLE requests (
    requester TEXT, target TEXT,
    PRIMARY KEY (requester, target)
);

CREATE TABLE messages (
    conv TEXT, sender TEXT, display TEXT,
    text TEXT, ts INTEGER, mid TEXT
);
-- Index: messages (conv, ts)

CREATE TABLE calls (
    room TEXT, member TEXT,
    PRIMARY KEY (room, member)
);

CREATE TABLE groups (
    gid TEXT PRIMARY KEY,
    name TEXT, created INTEGER
);

CREATE TABLE group_members (
    gid TEXT, member TEXT,
    PRIMARY KEY (gid, member)
);
```

### HTTP Endpoints

| Method | Path | What It Does |
|--------|------|-------------|
| POST | `/claim` | Claims or re-verifies a Cubeon name |
| GET | `/name/<name>` | Checks if a name exists / is online |
| GET | `/ws` | WebSocket upgrade (the realtime channel) |

All stateful requests are forwarded to the DO via `env.HUB.get(id).fetch(request)`.

### WebSocket Protocol

Every frame is a JSON object with a `t` (type) field. The protocol is documented in both `cubeon/friends.py` (client) and `cubeon-friends.js` (server) - they must stay in sync. `tools/test_friends.py` reads both files and asserts parity.

**Client → Server:**
| Type | Purpose |
|------|---------|
| `hello` | Authenticate (name + secret + version + status) |
| `add` | Send friend request |
| `accept` / `decline` | Respond to request |
| `remove` | Unfriend |
| `dm` | Direct message |
| `group_new` / `group_msg` / `group_leave` | Group chat |
| `version` / `status` | Update presence |
| `history` | Fetch recent messages |
| `typing` | Typing indicator |
| `call_invite` / `call_accept` / `call_decline` / `call_end` | Voice/P2P call lifecycle |
| `signal` | Opaque signalling (voice audio or P2P data) |

**Server → Client:**
| Type | Purpose |
|------|---------|
| `hello_ok` | Authenticated |
| `error` | Something was refused |
| `roster` | Full state (friends, requests, groups) |
| `presence` | One friend's status changed |
| `request` / `friend_added` / `friend_removed` | Friend graph changes |
| `group_created` / `group_update` | Group changes |
| `system` | Server-side notice |
| `dm` / `group_msg` / `history` | Chat messages (echoed back) |
| `call_*` / `signal` | Voice/P2P signalling (relayed) |

### Presence

A user is "online" iff at least one WebSocket carries their name. Derived from `getWebSockets()` every time (survives DO hibernation). When the last socket for a user closes, their friends are told they went offline.

### Chat History

Stored in SQLite, limited to 50 messages per conversation. Trimmed on write (never grows without bound). DM conversation keys are sorted canonical names joined with `:`.

### Hibernation

The DO uses the WebSocket Hibernation API: idle connections are evicted from memory and stop accruing duration charges. Nothing realtime is kept in instance state - every lookup derives from `getWebSockets()` + SQL.

### Voice/P2P Signalling

The `signal` message type carries opaque payloads between room members. The Worker never inspects the `data` field - it just routes it. This is how both voice audio and P2P world data ride the same channel:

- Voice: `data` contains WebRTC-style SDP offers/answers
- P2P: `data` contains `{kind: "p2p_offer", ...}` or `{kind: "p2p_answer", ...}` or mod sync chunks

---

## Deployment

All three workers are deployed manually via the Cloudflare dashboard editor. `wrangler.toml` files exist for local development (`wrangler dev`).

**No CI/CD for Workers** - this is a manual process. The launcher's Python code is built by GitHub Actions, but the Workers are deployed separately.

---

## Free Tier Limits

| Resource | Limit | How Cubeon Stays Under It |
|----------|-------|--------------------------|
| KV writes | ~1,000/day | Write-frugal publishing (only on change) |
| KV reads | 100,000/day | Cape texture inlined (zero reads) |
| KV storage | 1 GB | Skins are 2-8 KB each |
| Durable Object duration | 500,000 GB-s/day | Hibernation API (idle = no billing) |
| Durable Object storage | 5 GB | Chat limited to 50 msgs/conversation |
| Worker CPU time | 10 ms free / request | Minimal processing per request |
