[Documentation](../README.md) / Architecture

# Hosted services

Cubeon's desktop launcher uses Cloudflare Workers for online features and
Vercel for its website. Game files, instance content, local profiles and
Minecraft processes remain on the player's machine. See the
[architecture overview](overview.md) for launcher ownership and launch flow.

## Cloudflare Workers

Each service has its own source and Wrangler configuration under `worker/`.

| Service | Responsibility | Storage |
| --- | --- | --- |
| [Skins](../../worker/cubeon-skins.js) | Skin identity, username pointers, textures, capes and cosmetics | Cloudflare KV and the Workers Cache API |
| [Invites](../../worker/cubeon-invites.js) | Publish and resolve invite codes for host addresses | Cloudflare KV |
| [Friends](../../worker/cubeon-friends.js) | Name ownership, presence, chat, groups and signaling | One SQLite-backed Durable Object with WebSocket hibernation |
| [Downloads](../../worker/cubeon-downloads.js) | Release lookup and installer downloads | Cached GitHub release metadata |
| [Waitlist](../../worker/cubeon-waitlist.js) | Website email signup | Cloudflare KV |

The launcher owns friend state in `cubeon/friends_service.py`. The in-game
client accesses that state through the token-protected loopback bridge in
`cubeon/local_api.py`; it does not receive the launcher's private account secret.
Cloudflare's friends hub authenticates the client secret in the first WebSocket
frame and stores its SHA-256, rather than exposing the secret in a URL.

Skin and invite writes also require owner secrets. The Workers enforce request
validation, upload/body limits and per-IP throttles; the friends hub adds
per-action limits. The KV services use a `RATE_LIMITER` binding and an
in-isolate fallback where configured. These controls reduce abuse but do not
establish an account-wide request or write ceiling.

Storage has distinct retention rules. Invite records expire after 24 hours;
skin moderation reports expire after 30 days; the friends hub keeps the most
recent 50 messages per conversation. These bounded records do not imply that
all account, friend or texture records have an automatic deletion policy.
Mutable public skin profiles cache for 60 seconds, while content-addressed
textures cache immutably for a year. Keep username/avatar URLs on the mutable
policy. See the [Worker guide](../../worker/README.md) for cache behavior,
write budgets, throttling limits and deployment configuration.

Protocol references describe the route and message formats:

- [Skins and capes](../protocols/skins-api.md)
- [Invite codes](../protocols/invites-api.md)
- [Friends WebSocket](../protocols/friends-api.md)

Check the corresponding Worker source and contract tests when changing a
protocol. Client and service updates must preserve existing authentication
and compatibility behavior.

## Website and Doctor

The English website lives under `web/`, with the canonical origin
`https://www.ylet.online/`. The root and `web/` Vercel configurations support
repository-root and website-root deployments. Former locale routes redirect
to English pages. [Website search visibility](../development/website-seo.md)
describes canonical URLs, crawl files and verification.

Website Doctor performs local log checks in the browser. Its optional AI
analysis uses `POST /api/doctor`, handled by `web/api/doctor.js` with a root
`api/doctor.js` entry for repository-root deployments. Provider credentials
belong in server environment secrets. A plain static server supports the local
checks. See the [Doctor guide](../development/website-doctor.md) for redaction,
provider fallback, bounded requests and visitor limits.

## Deployment and verification

Use each service's checked-in Wrangler configuration and the
[Worker deployment guide](../../worker/README.md). The friends service needs
the declared SQLite Durable Object migration. Repository configuration and
passing offline tests do not establish which code or bindings are live.
Verify the intended deployed environment after a service change.

The Worker fixtures run without Cloudflare credentials:

```bash
node worker/test-worker.mjs
node worker/test-invites.mjs
node worker/test-skins-cache.mjs
node worker/test-downloads.mjs
```

Additional service fixtures live in `worker/test-*.mjs`. The
[testing guide](../development/testing.md) covers launcher contract tests and
browser checks. Report deployment checks separately from these offline tests.
