---
name: Throw in the Towel
description: A fantasy-football trading terminal — every player is a ticker, every projection a live price.
colors:
  bg: "#08090B"
  panel: "#0E1014"
  panel2: "#15181E"
  line: "#212630"
  line2: "#2C333F"
  ink: "#EAEEF4"
  dim: "#9AA2AF"
  faint: "#7E8794"
  red: "#FF3B47"
  red-deep: "#B71C26"
  up: "#24D08A"
  down: "#FF3B47"
  amber: "#F5A524"
  pos-rb: "#24D08A"
  pos-wr: "#5AA9FF"
  pos-te: "#F5A524"
  pos-qb: "#FF6FA5"
  white: "#FFFFFF"
typography:
  display:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "52px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "-1px"
    fontFeature: "'tnum' 1"
  headline:
    fontFamily: "Hanken Grotesk, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "21px"
    fontWeight: 700
    letterSpacing: "-0.4px"
  title:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "17px"
    fontWeight: 700
    fontFeature: "'tnum' 1"
  body:
    fontFamily: "Hanken Grotesk, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.35
  label:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "12px"
    fontWeight: 700
    letterSpacing: "0.5px"
  heroWide:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "60px"
    fontWeight: 700
    letterSpacing: "-1px"
  statNumber:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "34px"
    fontWeight: 700
  subhead:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "30px"
    fontWeight: 700
  delta:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "14px"
    fontWeight: 700
  bodySmall:
    fontFamily: "Hanken Grotesk, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  microLabel:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "11px"
    fontWeight: 700
    letterSpacing: "0.4px"
  microMeta:
    fontFamily: "Spline Sans Mono, ui-monospace, SFMono-Regular, Menlo, monospace"
    fontSize: "10px"
    fontWeight: 700
rounded:
  brandDot: "2px"
  chip: "5px"
  input: "8px"
  button: "9px"
  panel: "12px"
  hero: "14px"
spacing:
  xs: "6px"
  sm: "8px"
  md: "12px"
  lg: "14px"
  xl: "16px"
components:
  button-primary:
    backgroundColor: "{colors.red-deep}"
    textColor: "#FFFFFF"
    typography: "{typography.body}"
    rounded: "{rounded.button}"
    padding: "14px"
  chip-filter:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.dim}"
    rounded: "{rounded.chip}"
    padding: "7px 12px"
  chip-filter-active:
    backgroundColor: "rgba(255,59,71,0.12)"
    textColor: "{colors.red}"
    rounded: "{rounded.chip}"
  card:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.panel}"
  input:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.input}"
    padding: "11px 14px"
  pos-chip:
    backgroundColor: "transparent"
    textColor: "{colors.dim}"
    rounded: "{rounded.chip}"
    height: "20px"
---

# Design System: Throw in the Towel

## Overview

**Creative North Star: "The Towel Terminal"**

A fantasy roster read as a brokerage screen. Every player is a ticker, every projection a live price, every decision a trade. The interface is a near-black instrument panel: the readout *is* the interface, not a caption tucked inside a card. It refuses the category default outright — the navy-and-pitch-green card dashboard every fantasy app ships, and the generic dark-SaaS admin panel. Numbers carry the meaning; labels only name the lanes.

The field is a single cool near-black glass ground (#08090B) that owns the whole viewport. On top sit flat matte panels (#0E1014) separated by hairlines (#212630) — never floating drop-shadow cards. Density is brokerage-clean rather than Bloomberg-dense: large readouts, generous breathing room, one decision surfaced at a time. The build is phone-first (560px max width, bottom tab bar) and one-handed by design.

The signal discipline is the whole personality: one meaning for red. Red is the towel — down, loss, sell — and the brand mark and market-loss are the same color (#FF3B47) on purpose. Green (#24D08A) is up; amber (#F5A524) is the coded highlight / watch lane; a deep oxblood red (#B71C26) fills action buttons so white text clears AA. Character comes from mono readouts, coded color, and tick-flash motion — not from ornament. There are no decorative gradients on chrome, no glass-blur ornament, no emoji, and deliberately no colored glow halos.

**Key Characteristics:**
- Near-black glass ground, flat matte panels, hairline separation — no drop-shadow cards.
- One meaning for red: brand, down, loss, and sell are all the same signal.
- Every quantity in tabular mono; every label in grotesk.
- Live ticker tape + quote rows + gainers/losers board as the recurring instruments.
- Coded color everywhere: position, state, and direction each have a fixed hue.

## Colors

A cool near-black instrument palette with three signal hues (red/green/amber) and four position codes; neutrals do all the structural work.

### Primary
- **Towel Red** (`#FF3B47`): The one load-bearing signal. Down / loss / sell AND the brand mark — the square brand dot, the ● LIVE lozenge, the active-chip tint, active nav, the panel-title tick before every card heading. One color, one meaning.
- **Oxblood Deep** (`#B71C26`): The action fill. Flat-filled primary buttons, the picked-you chip, the send button, and "me" chat bubbles — chosen over bright red so white text passes AA on a filled surface.

### Secondary
- **Ticker Green** (`#24D08A`): Up / gain / start. Gainer column, the start-call alert border, high-value tags, the "hi" pill, and the RB position code.
- **Signal Amber** (`#F5A524`): Coded highlight / watch — the jackfield lane. The status badge, the note-card accent rule, medium-value pills, and the TE position code. Never used for up/down.

### Tertiary (position codes)
- **RB Green** (`#24D08A`), **WR Blue** (`#5AA9FF`), **TE Amber** (`#F5A524`), **QB Pink** (`#FF6FA5`): The four position codes, rendered as outline chips (colored border + colored text on transparent), never filled blocks.

### Neutral
- **Glass Ground** (`#08090B`): The single field color behind everything; a faint red radial wash sits at the top edge (6% opacity) as the only atmospheric touch.
- **Panel** (`#0E1014`): Matte panel / card / row surface.
- **Panel 2** (`#15181E`): The recessed sub-surface — trade chips, movers option pills, the star toggle rest state, fair/verdict-neutral fills.
- **Hairline** (`#212630`) and **Hairline 2** (`#2C333F`): The 1px separators that do all the depth work; the heavier line2 edges the hero and ticker LIVE divider.
- **Ink** (`#EAEEF4`): Primary text and readout digits.
- **Dim** (`#9AA2AF`) / **Faint** (`#7E8794`): Labels, captions, and de-emphasized metadata.

### Named Rules
**The One Red Rule.** Red means exactly one thing everywhere — the towel: down, loss, sell, and the brand. It is never repurposed for a neutral accent, a decorative fill, or a "primary CTA" tint. Up is green, watch is amber; nothing else borrows red.

**The Coded-Color Rule.** Position and state each own a fixed hue (RB green, WR blue, TE amber, QB pink; up green, down red, watch amber). A color's job is to be read, not decorated — the same hue never carries two meanings on one screen.

## Typography

**Display / Numeric Font:** Spline Sans Mono (with ui-monospace, SFMono-Regular, Menlo)
**Body / Label Font:** Hanken Grotesk (with -apple-system, Segoe UI, Roboto)

**Character:** A trading-terminal pairing — every quantity is set in tabular mono so digits align in columns and tick in place without reflow; every label and prose word is set in grotesk. The two never trade jobs.

### Hierarchy
- **Index Readout** (mono, 700, 52px, line-height 1, -1px tracking): The hero instrument — the big glowing-in-spirit projected-points / index number. Tabular.
- **Screen Heading** (grotesk, 700, 21px, -0.4px): The `h2` per-screen title.
- **Quote Number** (mono, 700, 17px, tabular): The right-aligned projection / price on every player quote row; also verdict and odds numbers scale up from this.
- **Body** (grotesk, 400, 15px, line-height 1.35): Prose, player names, note-card copy.
- **Label** (mono, 700, 12px, ~0.3–0.5px tracking): Panel titles, pills, option chips, nav labels, slot markers — the coded lane labels of the terminal.

### Named Rules
**The Numbers-in-Mono Rule.** Every quantity — prices, projections, percentages, deltas, odds, ticker symbols — is Spline Sans Mono with `font-variant-numeric: tabular-nums`. Every non-number label and every prose sentence is Hanken Grotesk. Mixing the two roles is off-world.

**The No-Small-Caps Rule.** Labels are sentence/normal case with modest tracking. The readability-floor pass explicitly stripped `text-transform:uppercase` and tightened letter-spacing on panel titles, call headers, and trade-box labels; do not reintroduce hard uppercase small-caps on labels.

## Layout

Phone-first, single column, centered at `max-width: 560px`. A sticky brand chrome bar sits at top; a sticky live ticker tape rides directly beneath it; a fixed bottom tab bar (with `env(safe-area-inset-bottom)` padding) anchors navigation. Screens swap in place with a 0.25s fade-up. Body padding reserves 76px at the bottom for the nav.

Rhythm is small and consistent: panels stack with 14px gaps; internal panel padding is ~12–14px; row padding is 11px 14px with 1px top hairlines between rows (first row borderless). Two-up grids (calls, movers, odds hero, trade sides) use a 1fr 1fr grid at 10px gap; the draft best-picks strip is a 5-column grid at 6px. Horizontal filter tab rows scroll on overflow rather than wrapping.

## Elevation & Depth

Flat by rule. There are no drop-shadow cards anywhere — `.card` explicitly sets `box-shadow: none`. Depth is carried entirely by tonal layering (ground → panel → panel2) and 1px hairlines. The only shadow in the system is a single 1px inset top highlight on the hero (`inset 0 1px 0 rgba(255,255,255,.03)`) that reads as a faint bevel on the one instrument readout, not as a lift.

### Named Rules
**The No-Float Rule.** Panels never float on a drop shadow. Separation is a hairline (`1px solid #212630`) and a tonal step, never a cast shadow. If a surface needs to feel raised, step its background up (panel → panel2) or brighten its border (line → line2).

**The No-Glow Rule.** The world was specified with a colored readout glow (nixie donation); the shipped build deliberately omitted it to honor the craft floor. Readouts are flat mono on flat panels. Do not add colored glow halos, text-shadow auras, or box-shadow glows to numbers or accents — instrument character comes from mono + coded color + tick-flash motion instead.

## Shapes

Soft-rectangular, quiet corners. A tight radius scale climbs by role: 5px on chips/pills/pos-codes, 6–8px on small controls and inputs, 9px on buttons, 12px on panels/cards, 14px on the hero. Position chips and coded pills are outline forms — a 1px colored border with colored text on a transparent (or barely-tinted, ~12–16% alpha) fill — never solid color blocks. The brand dot is a 2px-radius square (a terminal LED), not a circle. Panel titles carry a 3px × 11px red tick bar as their leading marker.

## Components

### Buttons
- **Shape:** Gently rounded (9px); full-width block CTAs.
- **Primary:** Flat oxblood-deep fill (`#B71C26`) with white text, grotesk 700 — the deep red keeps white text AA-legible on a filled surface. Padding 14px. Used for Generate Plan, Connect, and other commit actions.
- **Pick / small action:** Same oxblood fill at 6px radius, mono 700.
- **No gradient CTAs:** Buttons are flat fills, not gradient panels.

### Chips
- **Filter/tab chips:** Panel background, 1px hairline, dim mono text, 5–7px radius. Active state swaps to a red-tinted fill (`rgba(255,59,71,0.12)`) with a red border and red text.
- **Position chips:** Outline only — transparent fill, 1px border in the position code color, mono 700, ~30px min-width / 20px tall.
- **Value / injury tags:** Tinted pills (~14% alpha) in up-green / down-red / amber, 4–5px radius.

### Cards / Containers
- **Corner:** 12px panels; 14px hero.
- **Background:** Panel (`#0E1014`) on the glass ground; recessed elements step to panel2 (`#15181E`).
- **Shadow Strategy:** None — see Elevation & Depth. Hairline border only.
- **Border:** `1px solid #212630`; the hero and ticker use the heavier `#2C333F`.
- **Panel title:** Dim mono label with a leading 3px red tick bar (`.ct::before`).

### Inputs / Fields
- **Style:** Panel fill, 1px hairline, ink text, 8px radius, ~11–14px padding. Chat input is a 22px pill; the send button is a 44px oxblood circle.
- **Focus:** No custom glow ring; relies on the native focus outline over the hairline.

### Navigation
- **Bottom tab bar:** Fixed, translucent near-black with `backdrop-filter: blur(16px)`, top hairline, safe-area padding. Icons are inline stroked SVG (~21px); labels are tiny uppercase mono in faint gray. Active tab turns red (icon + label).

### Signature Component — Quote Row & Ticker Tape
The recurring instrument. A **quote row** is symbol/name (grotesk) · meta (dim mono) · right-aligned projection (mono 700) · coded pills · optional sparkline, separated from siblings by a 1px top hairline. The **ticker tape** is a sticky marquee (`@keyframes tk`, 90s linear, pause-on-press, edge mask) of `symbol · price · ▲▼ change` with a fixed ● LIVE lozenge on the left. On data update, movers tick-flash: a 1s green (`flashUp`) or red (`flashDn`) background pulse that decays back to panel. All motion is disabled under `prefers-reduced-motion`.

## Do's and Don'ts

### Do:
- **Do** set every quantity in Spline Sans Mono with `tabular-nums`, and every label/prose word in Hanken Grotesk.
- **Do** keep red for one meaning only — the towel: down, loss, sell, and the brand.
- **Do** separate surfaces with 1px hairlines (`#212630`) and tonal steps (bg → panel → panel2), not shadows.
- **Do** render position chips and coded pills as outline / low-alpha-tint forms in their fixed hue (RB green, WR blue, TE amber, QB pink).
- **Do** fill primary buttons with oxblood deep (`#B71C26`) so white text clears AA.
- **Do** convey liveness with tick-flash motion and the LIVE ticker, and disable all motion under `prefers-reduced-motion`.

### Don't:
- **Don't** float panels on drop shadows or add card lift — flat is the rule.
- **Don't** add colored glow halos, text-shadow, or box-shadow auras to readouts or accents (glow was deliberately cut).
- **Don't** put decorative gradients on chrome or buttons; gradients survive only as a functional bar fill.
- **Don't** hard-uppercase small-caps labels — the readability floor tuned them to normal case with modest tracking; keep it.
- **Don't** reach for navy + pitch-green fantasy-app defaults or generic dark-SaaS admin styling.
- **Don't** use emoji, and keep UI icons as the inline stroked-SVG set (data arrows ▲▼ are directional glyphs, not icons).
