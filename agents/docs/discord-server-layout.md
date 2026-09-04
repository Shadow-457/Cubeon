# Cubeon - Discord Server Layout

A reference layout for the official Cubeon community Discord. Cubeon is a
Minecraft launcher focused on **low-latency co-op**: relay-first P2P friend
sessions, one-click local server hosting, and auto-installed performance
plugins (Smooth mode). The server structure below reflects those features.

> Legend: `#` = text channel · `🔊` = voice channel · `📣` = announcement
> Roles and per-channel permissions are noted where they matter.

---

## 📣 Welcome & Info

| Channel | Purpose |
| --- | --- |
| `#welcome` | Bot-gated intro + rules acceptance (MEE6/Carl-bot). New members get the `@Member` role here. |
| `#announcements` | Release notes, downtime, new launcher builds. **Staff only.** |
| `#changelog` | Auto-posted from the Cubeon GitHub Releases webhook. |
| `#getting-started` | Pinned quick-start: install, pick a version, host or join. |
| `#faq` | Curated answers (crash fixes, Java versions, port forwarding, relay vs direct). |
| `#status` | Live status of the Cubeon relay/Worker backend (healthchecks webhook). |

---

## 🎮 Play Together (core feature: P2P friends)

| Channel | Purpose |
| --- | --- |
| `#find-a-friend` | Share your Cubeon invite code / friend handle to connect via the Friends tab. |
| `#relay-status` | Report "stuck on relay" / direct-upgrade issues; relay-fallback toasts explained here. |
| `#nat-type-help` | Help reading `probe_nat()` results (open/restrictive). |
| `#co-op-lfg` | Looking-for-group to start a session or hosted server. |
| `🔊 friend-voice-1` · `🔊 friend-voice-2` | Voice for active co-op sessions. |

> Friends connect peer-to-peer: the launcher does a **relay-first handshake**
> then upgrades to a direct connection when possible. Posts here should include
> the Cubeon version (`main.py` build date) when troubleshooting.

---

## 🖥️ Server Hosting

| Channel | Purpose |
| --- | --- |
| `#hosting-help` | Local server hosting: RAM, EULA, port sharing, playit.gg tunnel. |
| `#smooth-mode` | Smooth mode (low-ping optimization) support - LagFixer / Chunky / FarmControl on Paper. |
| `#plugin-talk` | Community plugin recommendations beyond the curated low-ping stack. |
| `#plugin-requests` | Ask for a plugin to be added to the in-launcher Plugins market. |
| `#server-showcase` | Screenshots/worlds hosted via Cubeon. |
| `🔊 hosting-voice` | Live help while setting up a server. |

> Smooth mode writes a **per-version flag** in Cubeon's config, so the switch
> stays ON across tab switches and settings saves - report if it ever flips.

---

## 🧩 Mods & Customization

| Channel | Purpose |
| --- | --- |
| `#mod-help` | Fabric/Forge/Quilt/NeoForge loader questions. |
| `#mod-recommendations` | Share modlists; mirrors the in-launcher recommendations. |
| `#skins-capes` | CustomSkinLoader support, skin/cape mirroring. |
| `#resource-packs` | Pack sharing and troubleshooting. |
| `#datapacks` | Vanilla tweaks and datapack help. |

---

## 🛠️ Support & Feedback

| Channel | Purpose |
| --- | --- |
| `#bug-reports` | Use the crash explainer output + logs. Template pinned. |
| `#feature-ideas` | Vote on suggestions (👍 reactions). |
| `#launcher-feedback` | General UX feedback (UI, fuzz/chaos testing stories welcome). |
| `#logs-and-crashes` | Paste `latest.log` / crash dumps (attach files, no huge inline). |
| `#dev-talk` | For contributors: `cubeon/` internals, Worker (`cubeon-friends.js`), relay protocol. |

---

## 🤖 Automation & Roles

| Channel | Purpose |
| --- | --- |
| `#role-select` | Reaction roles: `@Modder`, `@Hoster`, `@Beta-Tester`, `@Dev`. |
| `#bot-commands` | How to use the support bot (log parser, version lookup). |

**Roles (top → bottom)**
- `@Owner` / `@Admin` / `@Moderator` - staff.
- `@Beta-Tester` - early builds + `#dev-talk` read access.
- `@Hoster` / `@Modder` - interest tags from `#role-select`.
- `@Member` - post-rule-accept.
- `@New` - 24h grace, read-only until promoted.

---

## Suggested Category Order

```
📣 Welcome & Info
🎮 Play Together
🖥️ Server Hosting
🧩 Mods & Customization
🛠️ Support & Feedback
🤖 Automation & Roles
```

### Onboarding flow
1. Join → `#welcome` → accept rules → auto `@Member`.
2. React in `#role-select` to self-tag.
3. Read `#getting-started`, then drop into `#find-a-friend` or `#hosting-help`.
4. Crashes → run the in-launcher explainer, post in `#logs-and-crashes`.
