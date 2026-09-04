# Style Library

For each style: what it is, when it's earned, the motion language that belongs to it, and what makes it look cheap when done wrong.

Motion is part of the style decision, not a separate afterthought - a brutalist site with soft liquid easing reads as unintentional, the same way mixing corner-radius systems does. Pick the visual style and its matching motion language together in Step 2/3, and state both.

## Minimalism / Swiss

**What it is**: Heavy whitespace, strict grid, restrained type scale (often one or two weights of one typeface), near-monochrome palette with a single accent, almost no decorative elements. Depth communicated through spacing and type contrast, not shadows.

**Earned by**: premium/luxury, editorial, high-end B2B, legal/finance, architecture/design studios, anything where the product's confidence is supposed to speak instead of the UI shouting.

**Motion**: restrained and almost invisible. Short fades and small slide-ins (150-250ms), `--ease-premium-out`, no bounce or overshoot. Motion confirms a state changed; it should never be the thing the user notices.

**Looks cheap when**: whitespace is just "unstyled" rather than deliberate rhythm; type scale is just default sizes with no real hierarchy; it becomes minimalism-as-excuse-for-laziness (one headline, one paragraph, one button, nothing else considered).

## Glassmorphism

**What it is**: Translucent, blurred panels (backdrop-filter: blur) over a colorful or photographic background, thin light borders, soft glow. Depth via blur + layering, not solid shadows.

**Earned by**: dashboards, media/entertainment apps, modern consumer products, anything with a rich background to blur against. Works well as an *accent* on premium sites (glass nav bar, glass modal) even when it isn't the primary style.

**Motion**: liquid and fluid. Panels should feel like they're settling through a viscous medium - blur/opacity/scale transition together, longer smooth easing (300-500ms, `--ease-premium-in-out`), hover states gently morph (blur increases, border glow softens in) rather than snapping. Background blobs or gradient light sources can slowly drift/breathe continuously in the background. Avoid hard cuts or linear timing - nothing here should feel mechanical.

**Looks cheap when**: overused on every element so nothing reads as foreground/background anymore; used on a plain white background where there's nothing to blur, so it just looks like grey haze; paired with a text-stuffed pill (the exact "Verified Masters Across Pakistan" failure) - glass pills are for short tags, not sentences; motion that snaps instantly instead of flowing, which breaks the "liquid" illusion the style depends on.

## Claymorphism

**What it is**: Soft, puffy, rounded 3D shapes - heavy border-radius, soft inner+outer shadows giving an inflated, tactile "clay" look, pastel or saturated friendly palettes.

**Earned by**: playful consumer apps, kids' products, wellness/fitness apps, friendly onboarding flows, brands wanting to feel approachable and soft.

**Motion**: bouncy, tactile spring physics. Use `--ease-spring` with real overshoot on entrances and button presses - elements should squash slightly on press and pop back on release, like squeezing actual clay. Durations a touch longer than minimalist motion (250-350ms) so the bounce reads.

**Looks cheap when**: applied to serious/premium/B2B content (a law firm with clay buttons reads as a toy); overdone across an entire dense UI so everything looks bloated and low-information-density; shadows too heavy, making text hard to read; motion that's stiff/linear instead of springy, which defeats the tactile point of the style.

## Neumorphism (soft UI)

**What it is**: Elements that appear extruded from or pressed into a single-color background using matched dual shadows (light + dark), very low contrast between element and background.

**Earned by**: rarely the primary style for a full product - real accessibility problems (low contrast). Best used sparingly for physical-feeling controls (toggles, dials) inside an otherwise higher-contrast design, not as the whole UI.

**Motion**: minimal and physical. The only real motion is the press-state itself - shadow pair inverting instantly as an element goes from "extruded" to "pressed in," like a real physical button. No decorative motion elsewhere; the style is too low-contrast to support flourish without becoming muddier.

**Looks cheap when**: used site-wide, causing contrast/accessibility failures and a washed-out, hard-to-scan interface. Avoid as a primary style unless the user specifically wants this retro look and understands the tradeoff.

## Brutalism / neo-brutalism

**What it is**: Raw, high-contrast, unapologetically unpolished - visible borders, 0 or minimal border-radius, harsh drop shadows offset from shapes, bold/mono type, saturated flat colors, deliberately "undesigned" look.

**Earned by**: creative studios, portfolios, indie/dev tools, brands wanting to signal confidence and personality by rejecting the polished-SaaS look, youth/gaming-adjacent brands.

**Motion**: instant and mechanical, on purpose. Snap transitions with little or no easing (`linear` or `steps()`, not smooth curves), near-zero duration (0-100ms) or hard cuts instead of fades. Hover/press states can flip instantly (color invert, shadow jump from offset to flat) rather than transitioning smoothly. The lack of polish in the motion is the point - a brutalist site with soft liquid-glass easing reads as a mistake, not a contrast choice.

**Looks cheap when**: applied to a trust-critical business (finance, medical, legal) where users need to feel safety, not edge; when it's actually just "unstyled Tailwind" and not a deliberate raw aesthetic - the tell is inconsistency (some elements brutalist, some default-rounded) rather than commitment to the bit; smooth premium easing curves left in by default, which undercuts the raw feel.

## Flat design / Material Design

**What it is**: Solid fills, no gradients/textures/skeuomorphic cues, clear geometric shapes, a defined elevation system using layered shadows at fixed z-levels (Material's dp-based elevation), consistent 4px/8px grid, bold functional color used to signal state and hierarchy rather than decoration.

**Earned by**: cross-platform consumer apps (especially Android-native or Android-adjacent products), productivity/utility tools, government/civic services, anything prioritizing fast recognition and accessibility over visual flourish - clarity has to win over "premium feel."

**Motion**: purposeful and physics-based, not decorative. Material's own principle: motion should show *where things come from and go to* (a card expanding into a detail view, a FAB morphing into a sheet) rather than just fading in. Standard curve is a fast-out-slow-in ease (`cubic-bezier(0.4, 0, 0.2, 1)`), durations 200-300ms for most transitions, ripple feedback on tap targets. Motion clarifies navigation state, it doesn't add mood.

**Looks cheap when**: it's just "no shadows, no gradients" with no real elevation system underneath, so hierarchy collapses; color used decoratively instead of to signal actual state (primary action, selected, disabled); default Material component styling left completely unmodified, which reads as "unstyled Android app" rather than a deliberate flat-design choice; ripple/motion applied inconsistently across similar components.

## Editorial / content-first

**What it is**: Typography-led, generous line-height and measure, pull quotes, asymmetric text/image grids, minimal chrome. Borrowed from print/magazine design.

**Earned by**: blogs, publications, long-form content, personal essays/portfolios, brand storytelling pages.

**Motion**: calm, editorial reveal. Content fades/slides up gently on scroll (like a page settling into place), understated hover underlines on links, no flashy transforms. Motion should feel like turning a page, not launching an app.

**Looks cheap when**: type scale/hierarchy isn't actually designed (just default prose styling); images dropped in without real grid relationship to the text; line length too wide (bad reading measure); scroll animations that are too kinetic/bouncy for the tone.

## Dark-mode premium / "cinematic"

**What it is**: Near-black backgrounds, high-contrast single accent color, generous negative space, large confident type, subtle gradients/glows used sparingly as accent lighting rather than decoration, often paired with squircle cards and fine 1px borders.

**Earned by**: developer tools, AI/tech products, premium SaaS, gaming, anything wanting a modern high-end tech feel (this is a strong, currently very "in" pattern - but must be executed with real restraint, not just `bg-black` + default components).

**Motion**: smooth and confident, slightly slower than minimalist motion (300-450ms, `--ease-premium-in-out`). Glows can pulse or trail subtly on hover/focus; light parallax on scroll reads as "cinematic" if used sparingly. Motion should feel deliberate and expensive, never twitchy.

**Looks cheap when**: it's just default dark mode with unchanged component styling; glow/gradient overused until it looks like a template; text contrast too low against near-black; motion too fast/utilitarian, which fights the cinematic feel.

## Local-business warmth (not a formal "-ism" but a real category)

**What it is**: Photography-forward (real food/product photos, not stock-y illustration), warm accessible palette pulled from the brand (e.g., a bakery's actual packaging colors), clear trust signals (hours, location, reviews) presented as real content blocks - not tech-dashboard chrome. Type can be friendly but should still be legible and not overly playful/script-heavy for body text.

**Earned by**: restaurants, bakeries, dessert brands, local service businesses, import/retail - the category this user builds most often.

**Motion**: gentle and friendly. Soft fade-ins, small hover lifts on cards/photos (4-8px translate + soft shadow growth), nothing sharp or techy. Should feel warm and human, not like a SaaS dashboard.

**Looks cheap when**: it's dressed up like a SaaS product (glass cards, gradient blobs, dashboard-style stat widgets) instead of feeling like an actual physical, trustworthy local business; trust claims get stuffed into pill/badge shapes instead of presented as real testimonial/stat content; generic stock photography instead of the brand's real product photos.

## Skeuomorphic-lite

**What it is**: Restrained real-world material cues - subtle paper/fabric/brushed-metal textures, soft realistic shadows implying physical thickness, buttons that look genuinely pressable - without going full 2010s-skeuomorphism (no fake leather stitching or glossy bevels everywhere). Applied to a handful of key surfaces, not the whole UI.

**Earned by**: premium physical-product brands, high-end hospitality/real-estate, watch/craft/heritage brands - anything selling tactility and craftsmanship rather than "tech."

**Motion**: physical press/release. Buttons and toggles depress and lift with a real sense of weight (translateY + shadow depth change on press), slightly slower release than press. Avoid digital-feeling instant states - everything should feel like it has mass.

**Looks cheap when**: textures are applied everywhere instead of 2-3 key surfaces; shadows/bevels are so heavy it reads as dated 2012-skeuomorphism instead of a restrained modern nod to it; combined with flat/dashboard chrome elsewhere so it looks inconsistent rather than intentional.

## Aurora / gradient-mesh

**What it is**: Large, soft, multi-color gradient meshes (not a flat two-color blob) used as ambient background light - often animated slowly - paired with clean, mostly flat foreground UI (cards, type) that reads as high-contrast against the ambient color.

**Earned by**: AI/creative-tool products, music/media apps, launch/landing pages for products that want to feel "alive," modern consumer tech.

**Motion**: slow, continuous, ambient. The gradient mesh itself should drift/rotate/shift hue very slowly in the background (10-30s loops, never noticed as "animating," just felt as alive) while foreground UI motion stays calm and quick like minimalism. The ambient layer moves; the interface layer doesn't compete with it.

**Looks cheap when**: the gradient is a static two-stop blob instead of a real mesh; foreground elements also glow/blur, muddying the one-layer-moves-one-doesn't contrast; animation loop is fast/noticeable enough to be distracting rather than ambient.

## Retro-futurism / Y2K revival

**What it is**: Chrome/gradient text, glitch accents, scanlines, saturated cyber palettes (magenta/cyan/electric-blue), sharp geometric or bevel-edge shapes referencing early-2000s tech and 90s futurism, often mixed with pixel or mono display type.

**Earned by**: youth/gaming brands, music/streetwear/nightlife, experimental portfolios, brands deliberately signaling irony or nostalgia rather than polish-at-all-costs.

**Motion**: snappy and slightly glitchy on purpose. Fast digital transitions (100-200ms), occasional intentional glitch/flicker or chromatic-aberration flash on hover, scanline sweep on load. Motion should feel like a CRT powering on, not a smooth modern app.

**Looks cheap when**: applied to a trust-critical or premium/B2B brand where it reads as unserious; glitch effects overused until content is hard to read; mixed with soft premium squircles/shadows that fight the raw digital reference.

## Maximalism / kinetic

**What it is**: Deliberately dense and layered - large type mixed with small, overlapping elements, saturated multi-color palettes, collage-like composition. The opposite instinct from minimalism, used on purpose rather than as clutter.

**Earned by**: fashion, music, art/culture brands, youth-facing consumer products, anything where energy and personality are the pitch rather than restraint.

**Motion**: energetic and layered. Staggered entrance animations (elements arrive in sequence, not all at once), scroll-triggered kinetic type (words scale/rotate/slide as they enter view), marquee/ticker elements for supporting content. Motion should feel busy but choreographed - every element's timing offset deliberately, not randomly.

**Looks cheap when**: it's just clutter with no hierarchy (nothing anchors the eye); every element animates with the same timing so it feels chaotic instead of choreographed; used for content-heavy or trust-critical UI where density actively hurts comprehension.

## Monochrome luxury

**What it is**: Near-single-color palette (black/white/one metal tone like champagne-gold or bronze), extreme restraint even beyond standard minimalism, oversized confident type, very slow deliberate pacing, generous full-bleed imagery.

**Earned by**: high fashion, jewelry, watches, ultra-premium hospitality, brands where "expensive" itself is the message.

**Motion**: slow and cinematic-restrained - the slowest motion language in this library. Long fades (500-800ms), large deliberate scale/reveal transitions on hero imagery, no bounce, no glow, no color shift. Every transition should feel unhurried, like the brand has nothing to prove.

**Looks cheap when**: it's rushed - fast/snappy motion instantly breaks the luxury illusion; any accent color creeps in beyond the single metal tone; default component timing (200ms) left in, which reads as generic SaaS rather than deliberately slow.

## Organic / blob-shape

**What it is**: Irregular, hand-drawn-feeling blob shapes instead of rectangles/circles for containers, dividers, and accents; soft natural curves throughout; often paired with an earthy or botanical palette.

**Earned by**: wellness, beauty, food/beverage, sustainability-focused brands - anything wanting to feel natural and human rather than engineered.

**Motion**: fluid morphing. Blob shapes can slowly morph between states (using SVG path interpolation or CSS `border-radius` keyframes), hover states cause gentle shape distortion rather than a rigid scale/translate. Should feel organic and unhurried, related to but calmer than the glassmorphism "liquid" language.

**Looks cheap when**: blobs are just one generic background shape reused everywhere with no relationship to content; combined with sharp rectangular UI elsewhere so the organic language doesn't actually touch the interface, just the decoration.

## Choosing an accent technique

Once the primary style is picked, at most one secondary technique can be layered in for accents - e.g., a minimalist site with squircle clay-style primary buttons, or a dark-premium site with a glass nav bar. The accent should appear on 1-2 element types max (buttons, or nav, or cards - not all three), never throughout. When accenting with a second style, borrow that style's motion language only for the accented elements (e.g., the clay buttons get spring bounce, everything else keeps minimalist restraint) - don't let the accent's motion bleed into the primary style's elements.

## Nav patterns (pick one deliberately - see Step 4.5)

- **Logo-left / links-right, no dead-center nav**: logo anchors the left, links and CTA cluster right with generous gaps. Reads confident and asymmetric rather than the default centered bar. Good default for premium/product sites when nothing more specific is earned.
- **Split-center**: logo dead-center, nav links split evenly left and right of it. Feels editorial/boutique. Earned by fashion, studios, high-end local businesses.
- **Transparent-to-solid on scroll**: nav starts transparent/overlaid on the hero, solidifies (background + shadow/border) once the user scrolls past it. Earned by anything with a strong full-bleed hero image or video.
- **Off-canvas-first**: a minimal top bar (logo + single menu icon) that opens a full-screen or slide-in menu, even on desktop. Earned by brutalist, editorial, or portfolio sites where restraint is the point.
- **Vertical rail/sidebar**: nav lives on the left or right edge as a persistent column instead of a top bar. Earned by dashboards, admin tools, and content-heavy apps with many top-level sections.
- **Two-row stacked nav**: a slim utility row (contact info, language, account links) above a primary row (logo + main nav). Earned by e-commerce and content-heavy sites that need to surface more than 5-6 links.
- **Logo-only, links-on-interaction**: just a wordmark or icon until hovered/tapped, then links reveal. Earned by very minimal luxury or single-product brands where the nav shouldn't compete with the hero.

Match the pattern to the same category logic used in Step 1 - don't pick based on which one is easiest to code.
