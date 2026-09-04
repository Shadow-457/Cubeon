# Technical Details

Concrete implementation for the premium details mentioned in SKILL.md. Read the relevant section when you reach that step - don't try to hold all of this in memory.

## Squircle / G2-continuous curves

Standard CSS `border-radius` produces a circular arc (G1 continuity at best) - at high radius values on a small shape this is exactly what makes default "rounded-2xl" cards look like generic Tailwind output. True squircles (superellipse curves, G2-continuous) are what iOS icons and premium product UIs (Stripe, Linear, Arc) actually use - the curve's rate of change is smooth, not abrupt, so it reads as more refined at a glance even if most people can't say why.

**Easiest correct approach - CSS `corner-shape` (modern browsers) or fallback:**

```css
/* Modern (Chromium 2025+/Safari TP): true squircle via corner-shape */
.squircle {
  border-radius: 24px;
  corner-shape: squircle; /* superellipse corners instead of circular arcs */
}
```

**Universal fallback - SVG clipPath with a superellipse path**, generate the path with a small helper (n=4 or 5 gives an iOS-like squircle):

```js
// Generates an SVG path string for a superellipse (squircle) of given size/exponent
function squirclePath(width, height, n = 4, steps = 64) {
  const points = [];
  for (let i = 0; i <= steps; i++) {
    const t = (i / steps) * (Math.PI / 2);
    const x = Math.pow(Math.abs(Math.cos(t)), 2 / n) * Math.sign(Math.cos(t));
    const y = Math.pow(Math.abs(Math.sin(t)), 2 / n) * Math.sign(Math.sin(t));
    points.push([x, y]);
  }
  // Mirror into all four quadrants, then build path from full point set...
  // (use library `squircle-css` or `figma-squircle` npm package instead of hand-rolling in production)
}
```

**Practical recommendation**: in React/HTML artifacts, use the `figma-squircle` or `squircley` npm-style approach (generate a clip-path polygon/path once, apply via CSS `clip-path`) for hero cards, primary buttons, and feature panels on premium builds. For everything else, well-chosen standard `border-radius` is fine - reserve true squircles for the 2-4 hero surfaces where the extra fidelity is actually noticed.

## Skeleton loading screens

A skeleton should mirror the *exact geometry* of the content it's replacing - same widths, same corner radius language as the rest of the system, same layout grid. A generic gray box is not a real skeleton.

```css
.skeleton {
  background: linear-gradient(
    90deg,
    var(--skeleton-base) 25%,
    var(--skeleton-shimmer) 50%,
    var(--skeleton-base) 75%
  );
  background-size: 200% 100%;
  animation: shimmer 1.4s ease-in-out infinite;
  border-radius: inherit; /* match the real element's radius system */
}
@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

Build skeleton variants matching each real content shape used on the page (skeleton-card, skeleton-avatar, skeleton-text-line at the right widths) rather than one generic skeleton block reused everywhere.

## Custom easing curves

Never leave interactive transitions on default `ease` or `linear`. Premium products use deliberate cubic-beziers:

```css
:root {
  --ease-premium-out: cubic-bezier(0.16, 1, 0.3, 1);   /* strong deceleration, feels responsive */
  --ease-premium-in-out: cubic-bezier(0.65, 0, 0.35, 1); /* smooth both ends */
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);      /* slight overshoot, tactile */
}
```

Use `--ease-premium-out` for anything entering the screen (modals, dropdowns, hover-reveals), `--ease-spring` sparingly for tactile confirmations (button press, toggle), and keep durations short (150-250ms for micro-interactions, 300-400ms for larger transitions). Long/slow transitions on common interactions feel sluggish, not premium.

### Per-style easing tokens

These pair with the **Motion** entry for each style in `references/style-library.md` - pick the token set matching the chosen style, don't mix them:

```css
:root {
  /* Minimalism / editorial - restrained, quick */
  --ease-restrained: cubic-bezier(0.16, 1, 0.3, 1);
  --duration-restrained: 180ms;

  /* Glassmorphism / aurora / organic-blob - liquid, fluid */
  --ease-liquid: cubic-bezier(0.65, 0, 0.35, 1);
  --duration-liquid: 420ms;

  /* Claymorphism - bouncy spring */
  --ease-clay-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
  --duration-clay: 300ms;

  /* Brutalism - instant, mechanical, no easing */
  --ease-brutal: linear;
  --duration-brutal: 80ms; /* or 0ms for a hard cut */

  /* Dark-mode premium / cinematic - smooth, confident */
  --ease-cinematic: cubic-bezier(0.65, 0, 0.35, 1);
  --duration-cinematic: 380ms;

  /* Monochrome luxury - slow, unhurried */
  --ease-luxury: cubic-bezier(0.4, 0, 0.2, 1);
  --duration-luxury: 650ms;

  /* Retro-futurism / Y2K - snappy with a glitch beat */
  --ease-retro: cubic-bezier(0.2, 0, 0, 1);
  --duration-retro: 140ms;
}
```

Brutalism is the one deliberate exception to "always use a custom cubic-bezier" from the base rule above - for that style, `linear` (or no transition at all) is the correct, intentional choice, not an oversight.

## Elevation systems (pick one, stay consistent)

- **Shadow-based**: layered soft shadows (e.g., `0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.08)`), no borders, works for light-mode SaaS/product.
- **Border-based**: thin 1px borders (often semi-transparent), no or minimal shadow - reads as more premium/technical (Linear, Vercel-style dark UIs).
- **Blur/glass-based**: backdrop-filter + translucency communicates layering instead of shadow.
- **Flat/brutalist**: no elevation at all, or hard offset shadows with no blur (`4px 4px 0 #000`) as a deliberate graphic choice.

Do not mix more than one of these across a single page.

## Custom SVG icons instead of emoji or mismatched icon packs

- Match stroke width to the type weight in use (thin type → 1.5px stroke icons; bold/display type → 2-2.5px stroke).
- Match corner language: if the UI uses squircles, icon terminals should be rounded too (`stroke-linecap="round" stroke-linejoin="round"`); if brutalist/sharp, keep icon terminals sharp.
- Derive icon color from the same palette as the rest of the UI (usually the neutral/foreground color, with the accent color reserved for active/selected states) - never leave icons on a default gray that doesn't match anything else.
- For a quick custom set, generate simple line icons directly as inline SVG (`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor">`) sized consistently (usually 20-24px) so `currentColor` inherits the correct color per context automatically.

## Trust/status content - the right shape for the job

Given the specific failure this skill was written to prevent: a rounded/glass pill with a checkmark works for a **short status word** ("Verified", "Live", "New", "4.9★"). If the content is a sentence-length claim ("Verified Masters Across Pakistan"), use one of:

- A small icon + short label ("Verified") as the badge, with the fuller claim as normal text next to or below it.
- A stat/trust block: icon, bold number or short label, one line of supporting text underneath - not all inside one capsule.
- A horizontal trust bar: 3-4 short badges side by side ("500+ Clients", "10 Yrs", "24/7 Support") each individually short, rather than one long pill trying to hold a full sentence.
