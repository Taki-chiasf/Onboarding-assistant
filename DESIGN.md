# DESIGN.md — Onboarding Assistant web UI

## Visual world

Mistral-inspired operate surface (pinned by brief, recorded 2026-09), enriched in place (user direction, 2026-09-25): white ground divided by 1px hairlines, near-black ink, JetBrains Mono 11px uppercase micro-labels (tracking +0.14em) group lists, and one warm pixel ramp that does all the color work — in the authored monogram, the streaming cursor, text selection, the input caret, and now also gradient hairline accents (tab underline, active-list tick, composer focus draw). Light theme only.

## Tokens (`web/app/globals.css`)

- Surfaces: background `#FFFFFF`, secondary/hover `#F5F5F3`, border `#E6E6E3`
- Ink: foreground `#111111`, muted `#71706C`
- Action: primary fill `#111111` (hover 85%), destructive `#E61300`
- Brand ramp: yellow `#FFAF01`, orange `#FF8204`, vermilion `#FA500F`, red `#E61300`, crimson `#C4001D`
- Gradient utilities: `.bg-ramp` (horizontal) and `.bg-ramp-v` (vertical) — the ramp as 1–2px hairline accents; never a text fill
- Elevation: `--shadow-lift` — `0 1px 2px rgb(17 17 17 / 0.04), 0 8px 24px rgb(17 17 17 / 0.05)` — the one soft offset shadow, reserved for floating evidence panels, the focused composer, and lifted chips
- Ambient: `.ambient-wash` — two percentage-scaled warm ellipses (4–6% alpha) grounding the login hero and the chat empty state; ellipse radii size to the box so the gradient never clips
- Type: Inter (`font-sans`), JetBrains Mono (`font-mono`); conversation body 16px relaxed, chrome 14px, mono labels 11px, greeting 32px semibold
- Browser surfaces: selection orange/ink, caret `#FF8204`, thin 8px scrollbars `#D8D8D4`, favicon `app/icon.svg` (the monogram)

## Motion (`motion` v13, `web/lib/motion.tsx`)

Shared language, all through `MotionConfig reducedMotion="user"`:

- Timing: confidence ease `cubic-bezier(0.16, 1, 0.3, 1)`; routine changes 0.15–0.3s, entrances ≤ 0.45s, stagger steps 0.05s capped, exits faster than entrances
- Feedback: every control has spring press (`scale 0.97`, stiffness 500 / damping 30); send square `scale 0.88`
- Continuity: conversation switching is a keyed cross-fade rise (exit 0.18s y −8); Recent-list items use layout animation; a view key — not the conversation id — drives the switch so a mid-stream id assignment never remounts a streaming turn
- Entrances: login hero rises then persona rows cascade (delay 0.3s + 0.05s steps); chat empty state staggers mark, greeting, subline, chips; the monogram assembles cube by cube (0.045s steps, opacity + scale 0.8)
- Focal moment — the evidence cascade: when an answer grounds, its panel rises (spring 400/32), sources stagger in with 6px ramp docket dots, and a 2px ramp-gradient tab underline springs between tabs (`layoutId`)
- Composer: a 2px ramp underline draws (scaleX, origin left) along the bottom on focus, plus `focus-within:shadow-lift`
- Persona signing-in: pixel cursor plus a 1px ramp sweep repeating along the row's bottom edge
- Streaming: three 6px cursor cubes walk the ramp (yellow → orange → vermilion) with the CSS hard-blink (0.9s, 0.15s stagger)
- Reduced motion: transforms and layout animations are dropped, opacity/color transitions kept; the CSS blink guard dims the cursor static at 0.6

## Components

- `web/components/ui/button.tsx` — rounded-md; default h-10 near-black fill, sm h-8, outline hairline, ghost surface-hover, icon 32px; focus-visible ring `#111111` offset 2; spring whileTap
- `web/components/pixel-mark.tsx` — authored 8-cube ring monogram in the warm ramp (12×12 viewBox, 3-unit cubes), assembling on mount; `PixelCursor` ramp cubes hard-blink
- `web/components/transcript.tsx` — user turns as `#F5F5F3` rounded-2xl pills springing in; assistant turns as bare 16px text; clarify options stagger in; `SourcePanel` (evidence cascade) with mono underline tabs, docket dots, `shadow-lift`
- `web/components/chat.tsx` — 288px hairline sidebar (monogram, New conversation fill, mono RECENT list with layout-animated items and a 1px ramp-v tick on the active item, identity footer); 896px centered column; ambient-wash empty state (32px greeting with a `#FA500F` question mark, hovering chips); seamless composer with ramp focus draw and filled square send
- `web/components/persona-picker.tsx` — centered 480px column, ambient wash, hairline `divide-y` persona rows cascading in, arrow slides in on hover (md+), ramp sweep while signing in, always-visible arrow below md
- `web/lib/motion.tsx` — shared ease/spring/stagger/riseIn variants + `MotionProvider`

## Rules

- Depth: hairlines first; the one soft `shadow-lift` is reserved for things that genuinely float (evidence panels, the focused composer, lifted chips). No other elevation.
- Icons: lucide only; the pixel motif is reserved for the mark, the cursor, and the docket dots
- The ramp fills nothing larger than the monogram; as gradients it only draws hairlines (1–2px), ticks, and the cursor
- Answers stay plain text with evidence in the panel below; provenance (model, trace) lives in the trace tab
- Errors: `#E61300` text on 5% tint with 25% hairline border, naming the problem
