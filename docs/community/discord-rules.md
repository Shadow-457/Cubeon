# Cubeon Discord — rules, channels & moderation kit

Copy-paste ready. Written for a Minecraft-launcher community where the staff
are the developers: the rules are short on purpose, because a rule nobody can
apply in one message isn't a rule.

---

## 1. The short version (pin this in #rules / #start-here)

> **1.** Be decent. No harassment, slurs, hate speech or personal attacks.
> **2.** Keep it SFW. No NSFW or graphic content; use the spoiler tag.
> **3.** No piracy, cracked launchers, account sharing or selling anything.
> **4.** No cheating, exploits or unfair play in worlds/voice.
> **5.** No spam, self-promo, advertising, or link drops without permission.
> **6.** Support goes in the help channels. Staff never DM you first — that's a scam.
> **7.** Bug reports use the template and include your Cubeon version + diagnostics.
> **8.** Never share personal data, your auth key, or your identity secret.
> **9.** One account. No ban evasion, no leaks, no pre-release builds.
> **10.** Debate stays civil; keep arguments out of the server.
> **11.** English is the main language (others have their own channel).
> **12.** Follow staff instructions. Appeals go through #staff-tickets.

Rules marked 🔴 are **instant ban** (see the enforcement ladder).

---

## 2. Channel map (suggested)

| Channel | Purpose |
|---|---|
| `#start-here` | rules, official links, how to get the launcher |
| `#announcements` | read-only, staff posts releases/outages |
| `#changelog` | what changed in each version, written by Hamza |
| `#help-launcher` | install, Java, versions, launching |
| `#help-mods` | Fabric/Quilt/Forge/NeoForge + mods |
| `#help-modpacks` | modpack installs, CurseForge/Modrinth |
| `#help-skins-caps` | skins, capes, CSL |
| `#help-servers` | local servers, plugins, tunnels |
| `#bug-reports` | text channel, template enforced by a bot |
| `#suggestions` | forum, votes; Hamza marks Planned / Shipped / Won't do |
| `#showcase-skins-caps` | "look at this" |
| `#showcase-worlds` | P2P world builds and screenshots |
| `#screenshots` | clips and screenshots |
| `#looking-for` | LFG / looking for a world or pack |
| `#off-topic` | anything else |
| `#other-languages` | non-English chat |
| `#staff-chat` | staff only |
| `#staff-tickets` | user → staff, private (staff + ticket owner) |

**Voice:** `#hanging-out`, plus an AFK room for people who join but don't
talk. Keep the main voice empty so someone joining a call is joining *someone*.


---

## 3. The rules in full

**1. Be decent.** No harassment, insults, slurs, hate speech, dogpiling, or
attacking someone's appearance/identity. Don't DM staff to argue or to ask for
things you were told "no" to — that's a ban, not a negotiation. 🔴 Slurs and
hate speech = instant ban + delete.

**2. Keep it SFW.** No NSFW, nudity, gore, or shock content. Spoil story beats
with the spoiler tag. 🔴 Sexual content involving minors = instant ban and
report to Discord.

**3. No piracy.** Minecraft is free; Cubeon is free. Don't ask for, offer, or
link cracked launchers, account shares, keys, or "free premium" accounts. Don't
sell, trade, or gift accounts or keys.

**4. No cheating.** No clients, macros, unfair mods, exploit abuse, or
alt-account raids in shared/P2P worlds. Ask before using utility mods in a
world someone else hosts.

**5. No spam.** No self-promotion, server advertising, referral links, or
link-dropping. No ping/reaction/mention spam, no recruiting in DMs, no repeated
DMs to people who haven't answered you.

**6. Support lives in the help channels.** That's where staff see it, and where
the answer helps the next person. **Staff will never DM you first** — we only
DM you if *you* message *us*. Anyone who claims to be Cubeon staff in a DM,
asks for your identity secret, your auth key, or a "verification" code is
scamming you. Report it, don't paste the code.

**7. Bug reports use the template.** Include: what you did, what you expected,
what happened instead, your Cubeon version + Windows/Linux/Mac + game version,
and **the diagnostics** (in Cubeon: Settings → copy diagnostics, or the file
`~/.cubeon_launcher/cubeon.log`). A screenshot of the error is welcome; a
paragraph of speculation is not a bug report.

**8. Protect your data.** Don't post real names, emails, phone numbers, IPs, or
screenshots with personal info in them. **Never share your Cubeon identity
secret or `auth_key.json`/`identity.json`** — whoever holds that secret owns
your Cubeon name. If someone asks for it, it's a scam.

**9. One account, no evasion.** Don't use alts to dodge a ban, don't share
private/unreleased builds or leaked files, and don't repost Cubeon's source or
repackaged builds.

**10. Keep it civil.** Political/religious arguments and personal drama stay in
DMs. "Disagree with the decision, not the person" — and take it to
`#staff-tickets` if you think a decision is wrong.

**11. Language.** English is the main language; other languages have
`#other-languages`. Bad spelling in help channels is fine; bad faith isn't.

**12. Follow staff instructions.** Staff can lock a thread, mute, or remove a
message to keep things calm. If you think we were wrong, use
`#staff-tickets` — not the public channel.

---

## 4. Enforcement ladder

| Step | When | Tool |
|---|---|---|
| 1. Warning | first offence / unclear | staff note in `#staff-tickets` |
| 2. Timeout | repeat offence, or a heated argument | 12h → 24h mute |
| 3. Removal | clear rule break, no warning needed | kick |
| 4. Temporary ban | serious or repeated breaks | 7d → 30d |
| 5. Permanent ban | 🔴 rules, ban evasion, scams, harassment campaigns | ban + delete |

Skip the ladder (ban on first offence): 🔴 hate speech/harassment campaigns, 🔴
minor safety, doxxing, selling/asking for accounts or secrets, malware, ban
evasion.

Appeals: one `#staff-tickets` thread per ban, within 7 days. An admin involved

---

## 5. Staff setup

- **Owner (Hamza)** — everything; the only account that posts in `#announcements`.
- **Admin** — ban/kick, manage channels, pin, bulk delete.
- **Moderator** — delete, timeout, lock threads. No channel restructuring.
- **Helper** — badge only; answers help channels and escalates hard cases.
- **Bot** (`Cubeon Helper`) — `Manage Roles` **off**, admin off, can only read
  and post in its own channels. Never let a bot moderate.

Staff don't argue in public: one reply ("handled in `#staff-tickets`") and done.

---

## 6. Copy-paste templates

**Bug report** (`#bug-reports`)
```
**Version:** 1.0.2   **OS:** Windows 11   **Minecraft:** 1.21.1 (Fabric)
**What I did:** <steps>
**Expected:** <what should have happened>
**Instead:** <what happened — paste the full error text>
**Diagnostics:** <paste from Cubeon → Settings → copy diagnostics>
**Already tried:** <restart, re-download, other version...>
```

**Help question** (`#help-*`)
```
**What are you trying to do?**
**Cubeon version + OS:**
**Minecraft version + loader (vanilla/Fabric/Quilt/Forge/NeoForge):**
**What happened / full error text:**
**Diagnostics:** <if it's an error>
```

**Moderation DM** (private, matter-of-fact, no lecture)
```
Hey <name> — you <did X> in #<channel> (<link>), which is rule <n>: <quote the
rule>. Because <reason>, this is a <24h timeout / 7-day ban>.
It expires <time/date>. If you think this is wrong, open a ticket in
#staff-tickets. — <mod>
```

**Changelog post** (`#changelog`)
```
**v1.0.2** — <one line>
- Fixed: <user-visible fix>
- Fixed: <another>
- Changed: <behaviour change>
- Known: <if anything is still broken>
Upgrade: <in-app update / site link>
```

**Anti-scam banner** (pin in `#start-here` and `#help-launcher`)
```
⚠️ We will never DM you first, and we will never ask for your Cubeon secret,
your auth key, or a verification code. Official downloads are only on the
official site. If someone does any of the above: block, report, and tell staff.
```

---

## 7. Keeping it maintainable

- Pin one message in `#start-here` and **edit it in place** — never repost the
  rules, or the "latest rules" link rots.
- Review the rules when a feature ships (pre-release rule 9) or after the first
  time you actually need a rule you didn't have — rules should be written after
  the incident, not before it.
- If a rule causes an argument in `#staff-chat` more than once a month, either
  the wording is unclear or the rule is wrong. Fix the rule, not the member.

in the decision doesn't review their own ban.
