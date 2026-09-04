---
name: premium-ui-design
description: Use this whenever building or redesigning a website, landing page, web app UI, or any frontend interface, even if the user just says "build me a site" or "make a landing page" without mentioning design explicitly. Forces a deliberate design-system decision (choosing which visual language fits this specific site, such as glassmorphism, claymorphism, brutalism, minimalism, neumorphism, or editorial) instead of defaulting to a generic "AI-website" look. Covers premium micro-details like G2/squircle curves, skeleton loading states, custom SVG iconography, motion, and spacing systems, plus a hard list of things to never do, such as chip/pill/badge text bubbles holding a full sentence like "Verified Masters Across Pakistan", emoji used as icons, and template-y layouts. Trigger this for any HTML/React/frontend-design work, not just when the user explicitly asks for "good design."
---

# Premium UI Design

Most AI-generated websites look the same: a hero with a centered headline, a soft pastel gradient blob, rounded-2xl cards with drop shadows, an emoji next to every heading, and a pill-shaped badge with a checkmark and a sentence crammed inside it. This skill exists to stop that pattern. Every project must go through a real design decision, not a default.

## The workflow - do this every time, in order

### Step 1: Classify the site before writing any code

Ask (yourself, and the user if genuinely ambiguous): what *kind* of thing is this, really?

- **Premium / luxury / high-trust** (finance, real estate, legal, medical, high-end agency, B2B SaaS for enterprise) → restraint, precision, whitespace, high-end type, subtle motion.
- **Product / consumer app** (SaaS tool, marketplace, productivity app) → clarity-first, functional hierarchy, room for glass/clay accents but never at the cost of legibility.
- **Creative / portfolio / studio** (design agency, photographer, artist, indie brand) → the design *is* the pitch - most license to be bold, brutalist, experimental.
- **Local business / services** (the food/dessert/import businesses this user often builds) → warmth + credibility. Needs to look established and trustworthy fast, not techy or cold. Resist the urge to make a bakery site look like a crypto dashboard.
- **Editorial / content / blog** → typography carries everything. Grid, rhythm, reading comfort over decoration.
- **Playful / gaming / youth brand** → can be maximalist, high-contrast, kinetic - but "playful" is not an excuse for clutter or emoji-as-icons.

Read `references/style-library.md` before picking - it has the actual visual languages (glassmorphism, claymorphism, neumorphism, brutalism, minimalism/Swiss, editorial, dark-mode-premium, skeuomorphic-lite, flat design/Material Design, aurora/gradient-mesh, retro-futurism/Y2K, maximalism/kinetic, monochrome luxury, organic/blob-shape) mapped to when each one is earned, the motion language that belongs to each one, and what makes each one look cheap when done wrong.

### Step 2: Pick ONE primary style + at most one accent technique

Never blend three aesthetics. Pick a primary language for the whole site, and at most one secondary technique for accents (e.g., primarily minimalist/Swiss with clay-style buttons as the one tactile accent). State the choice explicitly in your plan before building: "This is a [type] site, so I'm going with [style] because [reason tied to the site's actual purpose, not because it looks nice]."

If it's genuinely unclear which bucket the site falls into, or the user has strong existing brand material (logo, colors, an existing site to match), use `ask_user_input_v0` once rather than guessing - but default to picking and stating a direction rather than asking, since most requests have enough context.

### Step 3: Build the actual design system before touching layout

Don't start writing hero sections. Decide first, and keep it consistent everywhere:

- **Corner radius language**: pick one curve system and stick to it. For premium/high-end work, prefer true **squircle / G2-continuous curves** (superellipse, not CSS border-radius circular arcs) on primary surfaces - see `references/technical-details.md` for the exact SVG/CSS approach. For brutalist/editorial, radius is often 0 everywhere on purpose.
- **Spacing scale**: pick a base unit (commonly 4px or 8px) and only use multiples of it. No arbitrary padding values.
- **Type system**: a display face + a text face, max two families. Set a real type scale (not just text-sm/base/lg/xl defaults) - premium sites usually have larger, more confident headline sizes and tighter tracking than default Tailwind gives you.
- **Color**: derive an actual palette (a primary, a neutral ramp, one accent) - never leave default Tailwind slate/blue/indigo untouched, that's the single biggest tell of an unstyled AI site. **Default to a light theme unless dark mode is actually earned** - see the rule below.
- **Elevation/depth model**: decide how depth is communicated - shadows, borders, blur, or flatness - and use only that method throughout. Mixing shadow-heavy cards with flat brutalist sections in the same page reads as unintentional.
- **Iconography**: custom SVGs matching the palette and stroke-weight of the rest of the UI - never emoji, never mismatched icon-pack styles. See the hard rules below.
- **Loading/empty/error states**: premium products show skeleton loading screens (shaped placeholders matching final content geometry), not spinners alone, and not blank flashes. Design these as part of the system, not an afterthought.
- **Motion**: the motion language is dictated by the style pick from Step 2, not a separate generic choice. Brutalism gets instant/snap transitions with no easing; glassmorphism and aurora/gradient-mesh get slow liquid, fluid easing; claymorphism gets bouncy spring physics; monochrome luxury gets very slow cinematic-restrained fades; dark-mode premium gets smooth confident easing with sparing glow. See the **Motion** entry under each style in `references/style-library.md` before deciding - never default to the same generic fade-and-slide for every project regardless of style.

`references/technical-details.md` has concrete CSS/SVG snippets for squircles, skeleton screens, custom easing curves, and depth systems - read it during this step, don't rely on memory for the exact math.

### Step 3.5: Derive at least two decisions from the specific brand, not the category

This is the step that actually prevents "generic," and it's easy to skip because the result still looks tasteful. A common failure mode: correctly avoiding the old cliché (glass pills, emoji, centered-hero SaaS) but landing on a *different* templated look - e.g. warm cream background + burgundy/dark-brown accent + editorial serif display type is currently the default "premium bakery/DTC" aesthetic across the whole industry, the same way rounded-2xl cards were the default SaaS aesthetic. Picking a style bucket from Step 1-2 correctly is necessary but not sufficient - if you'd make the same palette and type choice for any bakery brand, it's still generic, just generic-in-a-different-decade.

Before building, name at least two concrete design decisions that come from *this specific brand* and would be wrong for a different business in the same category:

- **Color**: don't reach for the category default (bakery → cream/terracotta/sage; fintech → navy/electric-blue; dev tool → near-black/single-accent) unless the brand's actual materials point there. Pull the palette from something real - the user's product photography, an existing logo, a described brand feeling - not from "what this vertical usually looks like." If there's no existing brand material, pick a color decision that's specific rather than safe (an unexpected accent, an unusual pairing) and state why it fits this brand's personality, not its category.
- **A structural motif tied to the product/brand**, not a generic section shape. E.g., if the product comes in boxes, let a box/container shape actually organize the grid instead of using generic equal-width cards. If the brand's identity is "small batch, handmade," let something in the layout feel handmade/imperfect rather than a perfectly regular grid. The motif should be something you couldn't paste onto a different brand's site unchanged.
- **At least one section that breaks the "hero / stats row / three-icon-list / testimonial-card" assembly-line structure.** That exact sequence (regardless of skin) is itself a template now. Reorder, merge, or replace one of these blocks with something built for this brand's actual content instead of the default slot.

If you can't name two brand-specific decisions, that's a signal you designed the category, not the client - go back and find them before writing code.

### Step 4: Build with intentional asymmetry

Generic AI sites are symmetric and centered by default: centered hero, 3-equal-column features, centered CTA. Real premium sites break this on purpose - offset grids, asymmetric hero splits, varied card sizes in a bento-style grid, content that bleeds to the edge. Not randomness - an intentional grid that just isn't lazily centered every time. Vary section rhythm (don't repeat the same padding/background/layout pattern for every single section down the page).

### Step 4.5: Pick the nav pattern deliberately - don't default to logo-left/links-center/CTA-right

The navbar is the single most repeated element across builds because it's usually the first thing written and gets the least design thought. Before building it, actively choose from more than one option instead of reaching for the same horizontal bar every time. Options to actually consider (see `references/style-library.md` for the full list with when each is earned):

- Logo-left, links-right, no center-nav (asymmetric, works for most premium/product sites)
- Split/centered logo with nav links divided left and right of it
- Minimal/transparent nav that solidifies or shrinks on scroll
- Off-canvas / hamburger-first even on desktop, for editorial or brutalist sites
- A vertical rail or sidebar nav instead of a top bar, for dashboards/apps
- A stacked two-row nav (utility row + primary row) for content-heavy or e-commerce sites
- Logo-only nav that reveals links on interaction, for very minimal/luxury brands

State which pattern was picked and why it fits this brand, the same way Step 2 states the style choice. Defaulting to logo-left/links-center/button-right without considering an alternative is the same failure mode as defaulting to the generic AI-site template in Step 3 - treat it as part of Step 3.5's structural-motif requirement, not a separate afterthought.

## Hard rules - never do these, regardless of what's asked

1. **Never put a full sentence or long label inside a pill/chip/badge shape.** A rounded pill with a checkmark is for a short status word ("Verified", "Active", "New") - not a sentence like "Verified Masters Across Pakistan" stretched across an oval. If the content is a claim or a piece of copy, it belongs in a text line, a card, or a stat block - not squeezed into a capsule that was designed for a 1-2 word tag. This exact failure (rounded glass pill + checkmark + long sentence) is a known bad pattern - never reproduce it, on any project, regardless of framing.
2. **Never use emoji as icons, bullets, or decoration in an app or website UI.** Not in headings, not in feature lists, not in buttons, not in empty states. Use custom SVG icons that match the site's stroke weight, corner language, and color system instead. (Emoji are fine only in casual chat-style copy the user explicitly writes as dialogue/messages, never as UI iconography.)
3. **Never leave default framework colors/spacing untouched.** No unmodified Tailwind slate-500/blue-600 palettes, no default shadow-md on everything, no unstyled default focus rings.
4. **Never default to the generic AI-site template**: centered hero + tagline + two CTA buttons + gradient blob + three equal feature cards with an icon-title-paragraph each + centered final CTA. If your plan matches this shape almost exactly, change the layout before building.
5. **Never mix corner-radius systems** (sharp 0 corners next to circular pill buttons next to squircle cards) unless it's a deliberate, stated contrast choice tied to the brand.
6. **Never skip loading/empty states** in interactive builds - a bare spinner or a flash of unstyled content is a tell of unfinished work.
7. **Never let "tasteful" substitute for "specific."** A well-executed style pick (nice type, coherent palette, no clashing radii) can still be generic if it's just the current default look for that business category. Cream/burgundy/editorial-serif for bakeries, near-black/single-accent for dev tools, navy/electric-blue for fintech - these are becoming the new templates. Passing Step 3.5 (two brand-specific decisions) is mandatory, not optional polish.
8. **Never reuse the same section-sequence skeleton unexamined**: hero → stat row with dividers → icon-title-description list beside a testimonial card → CTA. This shape now reads as templated on its own, independent of the visual skin applied to it.
9. **Never default to the same logo-left / centered-links / CTA-right navbar on every project.** Do Step 4.5 for real - pick a nav pattern that fits this specific brand instead of reusing whatever was built last time.
10. **Never use the same motion language regardless of style.** A brutalist site with smooth liquid easing, or a glassmorphic site with instant snap transitions, is as inconsistent as mixing corner-radius systems. Motion is a property of the style choice - look up the matching **Motion** entry in `references/style-library.md` and use it, not a generic fade-and-slide applied everywhere by default.
11. **Default to a light theme.** Dark mode is only earned when the category genuinely calls for it (dev tools, AI/tech products, gaming, premium SaaS going for the "dark-mode-premium/cinematic" look from the style library) or the user explicitly asks for it. Don't reach for `bg-black` by default because it looks moody or technical - for local businesses, e-commerce, editorial, wellness, finance-for-consumers, and most brand/marketing sites, a well-built light theme reads as more trustworthy and legible. If genuinely unsure, build light.

## Quick reference

- Style options + when each is earned → `references/style-library.md`
- Squircle/G2 curves, skeleton screens, easing curves, elevation systems, custom SVG icon approach → `references/technical-details.md`

Always state your style decision and reasoning briefly before building, so the user can redirect early if it's wrong - don't silently pick and build 500 lines before they see the direction.

## When the user asks for 3D / WebGL / shader / OpenGL-style visuals

If the user explicitly asks for something 3D, a shader effect, a WebGL scene, particle effects, or anything described as "OpenGL stuff," build an actual real-time WebGL/Three.js implementation - not a static image, not a CSS-only fake, not a video loop pretending to be interactive. Specifically:

- Use real `<canvas>` + WebGL (Three.js is available in React artifacts - `import * as THREE from 'three'`) so the result is genuinely rendered and interactive (responds to mouse/scroll/time), not a pre-baked asset.
- Don't substitute a CSS gradient animation, an SVG filter, or a static "3D-looking" screenshot when the user asked for an actual 3D/shader effect - that's faking it, and it's noticeably worse than the real thing once they interact with it.
- Match it to the brand's established design system (Step 3) rather than dropping in a generic demo effect - e.g. for a brutalist/dev-tool brand, a raw wireframe, glitch, or data-driven visual fits; for a soft/premium brand, a smooth ambient particle or gradient-mesh shader fits. The effect should look like it belongs to this site, not like a copy-pasted CodePen demo.
- Keep performance sane: cap particle/geometry counts reasonably, pause/reduce work when off-screen, and provide a static fallback state if WebGL context creation fails, so the rest of the page still works.
- This applies whenever real-time 3D/shader visuals are requested - it's not limited to any one style bucket from `references/style-library.md`.
