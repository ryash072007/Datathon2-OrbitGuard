---
version: alpha
colors:
  primary: "#2a78d6"
  background: "#f4f4f2"
  surface: "#fcfcfb"
  text: "#0b0b0b"
  danger: "#b42d2d"
typography:
  sans:
    fontFamily: "IBM Plex Sans, system-ui, sans-serif"
  mono:
    fontFamily: "IBM Plex Mono, ui-monospace, monospace"
rounded:
  panel: "8px"
  control: "6px"
omitted:
  - section: spacing
    reason: "Runtime CSS owns the established spacing system."
  - section: components
    reason: "Shared React primitives and CSS remain canonical."
---

# OrbitGuard console

## Overview
An orbital risk instrument for operators and datathon judges. The signature is IBM Plex typography, restrained blue actions, and explicit uncertainty beside every claim. Preserve the original console: Encounters opens by default, followed by Manoeuvre planning and Validation. Additional explanatory content belongs in an optional final How it works tab. Avoid decorative telemetry, invented metrics, or an implied live spacecraft connection.

## Colors
`frontend/src/style.css` is the canonical runtime token source. Frontmatter records its light palette; CSS also owns dark theme values. Blue identifies actions and the controlled satellite, orange the primary object, green another object. Status includes text and an icon; color alone never communicates acceptance.

## Typography
IBM Plex Sans carries headings, controls and explanatory prose. IBM Plex Mono is reserved for fingerprints and runtime details. Tables use tabular numerals. Explain Pc, CDM, TCA and metric definitions through shared keyboard-accessible terms.

## Layout
The natural-height page has a 1280px maximum width with 24px side padding. Optional How it works content separates historical forecasting from synthetic planning in two tracks. Its evidence uses a three-column comparison that stacks on narrow screens. Preserve existing page layouts. Tables own horizontal overflow; they do not constrain the page height.

## Elevation & Depth
Flat bordered panels; shadows only on tooltips. The header remains visible during document scrolling.

## Shapes
Panels use 8px radii, controls 6px. Preserve existing density and avoid ornamental geometry.

## Components
`ui.tsx` owns loading, empty, notice, status, tooltip and async request behavior. `App.tsx` owns navigation and evidence download. Lucide supplies functional icons. Charts read runtime CSS tokens.

## Do's and Don'ts
Show artifact-derived numbers and unavailable states. Distinguish ranking from threshold detection, training validation from held-out results, current server from benchmark environment, and geometry from probability. Use motion only for progress or user-controlled replay; honor reduced motion.
