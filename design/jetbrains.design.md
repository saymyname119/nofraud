---
version: alpha
name: Anthropic
description: "Anthropic is an AI safety and research company that's working to build reliable, interpretable, and steerable AI systems."
sourceUrl: "https://www.anthropic.com"

colors:
  primary: "#141413"
  on-primary: "#ffffff"
  background: "#faf9f5"
  surface: "#141413"
  border: "#141413"
  text: "#141413"
  text-muted: "#faf9f5"

typography:
  display:
    fontFamily: "Anthropic Sans, Arial, sans-serif"
    fontSize: 58px
    fontWeight: 700
    lineHeight: 1.1
  heading:
    fontFamily: "Anthropic Sans, Arial, sans-serif"
    fontSize: 58px
    fontWeight: 700
    lineHeight: 1.1
  body:
    fontFamily: "Anthropic Sans, Arial, sans-serif"
    fontSize: 12px
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: -0.24px
  mono:
    fontFamily: "Anthropic Mono, Arial, sans-serif"
    fontSize: 16px
    fontWeight: 400
    lineHeight: 1.4

spacing:
  base: 2px
  scale: [2, 4, 8, 12, 16, 22, 58, 68]

radius:
  sm: 8px
  md: 16px
  lg: 24px

shadows:
  card: "rgba(0, 0, 0, 0.01) 0px 2px 2px 0px, rgba(0, 0, 0, 0.02) 0px 4px 4px 0px, rgba(0, 0, 0, 0.04) 0px 16px 24px 0px"
  elevated: "rgba(0, 0, 0, 0.01) 0px 2px 2px 0px, rgba(0, 0, 0, 0.02) 0px 4px 4px 0px, rgba(0, 0, 0, 0.04) 0px 16px 24px 0px"

motion:
  duration-fast: 100ms
  duration-base: 200ms
  duration-slow: 800ms
  easing: "cubic-bezier(0.16, 1, 0.3, 1)"

breakpoints: [768px]
---

## Rationale

Anthropic's design system reflects a organization positioned at the intersection of cutting-edge AI research and public trust. The palette is deliberately restrained—a near-black primary (#141413) paired with a warm, off-white background (#faf9f5)—creating high contrast and visual clarity without coldness. This choice signals both rigor (the deep charcoal suggests seriousness and stability) and approachability (the cream undertone softens institutional formality). The typography stack centers on a custom sans-serif (Anthropic Sans), reinforcing brand identity while maintaining technical credibility through a dedicated monospace face.

The spacing and sizing strategy is hierarchical but compact. Display and heading scales both anchor at 58px with tight 1.1 line heights, demanding attention for key messages about safety and research leadership. Body text at 12px with negative letter-spacing (-0.24px) tightens the visual rhythm, creating density that rewards close reading—appropriate for an audience expected to engage seriously with research content. The 8-step spacing scale (capped at 72px) ensures predictable, grid-aligned layouts that feel methodical rather than organic.

Motion is purposefully refined: the easing curve (cubic-bezier(0.16, 1, 0.3, 1)) favors quick, snappy responses at 100–200ms, reinforcing responsiveness without distraction. Shadows are whisper-soft, barely visible at card and elevated levels, maintaining minimalist aesthetic while providing necessary layering cues. A single breakpoint at 768px signals mobile-first thinking with a clean tablet/desktop separation. Together, these decisions project intellectual rigor, trustworthiness, and clarity—essential for a safety-focused AI company building credibility with researchers, practitioners, and the public.

## 1. Visual Theme & Atmosphere

The design language is **minimalist institutional**—recalling university research labs and forward-thinking tech rather than playful consumer products. The achromatic core (nearly black surface and cream background) conveys seriousness and neutrality, letting content and product capabilities speak loudly. The warm off-white background (#faf9f5) prevents clinical coldness; it's inviting enough for long-form reading without sacrificing authority.

Generous use of negative space and restrained layering (card shadows are nearly imperceptible) creates an uncluttered, focused environment. The overall mood is **confident but not arrogant**—appropriate for a company discussing safety concerns in AI, where humility and precision matter.

## 2. Color System

**Primary Palette:**
- **Primary (#141413):** Near-black, used for text, borders, and surfaces. Provides structural anchoring and maximum contrast.
- **On-Primary (#ffffff):** Pure white for text and elements atop dark surfaces (inverse contrast scenarios).
- **Background (#faf9f5):** Warm off-white, the dominant page surface. Slight yellow undertone humanizes the interface.
- **Surface (#141413):** Identical to primary; dark cards and UI containers maintain visual consistency.
- **Border (#141413):** Same as primary, ensuring borders feel structural and intentional rather than decorative.
- **Text (#141413):** Defaults to primary, reinforcing monochromatic hierarchy.
- **Text-Muted (#faf9f5):** Reverse of background—used sparingly for tertiary information or disabled states.

**Rationale:** The two-color system eliminates ambiguity. Every element is either dark (content, interface) or light (background). Accent colors are absent from the measured tokens, suggesting the site relies on interaction states, opacity shifts, or component-level color for secondary messaging. This restraint amplifies impact when color *is* used (e.g., a CTA button or link).

## 3. Typography

**Font Families:**
- **Anthropic Sans:** Custom sans-serif for display, heading, and body. Provides brand singularity and visual consistency across hierarchies.
- **Anthropic Mono:** Custom monospace for code, data, or technical content. Ensures readability in AI/research contexts.

**Scale & Hierarchy:**
- **Display & Heading:** Both 58px, weight 700, line-height 1.1. Compact vertical spacing concentrates visual weight for hero statements ("AI research and products that put safety at the frontier"). The tight leading emphasizes urgency and confidence.
- **Body:** 12px, weight 400, line-height 1.4, letter-spacing -0.24px. Unusually small (compared to contemporary 16px norms), but the negative tracking tightens spacing, making 12px feel more compact and controlled. Suitable for dense research content, pricing tables, and secondary information.
- **Mono:** 16px, weight 400, line-height 1.4. Larger than body to ensure code and technical references stand out and remain legible.

**Intention:** The system prioritizes density and precision over warm readability. Users visiting Anthropic are expected to be engaged, technically literate readers—the cramped 12px body sends a signal: "serious content ahead."

## 4. Components & Patterns

Based on the harvested CTAs ("Try Claude," "Pricing," "Contact sales," "Download app") and measured tokens, the component library likely includes:

- **Primary Button:** Dark background (#141413), white text, likely 8px or 16px border-radius (sm or md), subtle card shadow for depth.
- **Secondary/Link:** Likely dark text on transparent or light background, underline or weight emphasis on hover.
- **Cards & Containers:** Minimal shadows (card shadow is ~0.01–0.04 opacity), 8–24px radius for soft but modern appearance.
- **Input Fields:** Dark borders (#141413), light background (#faf9f5), small body text (12px).
- **Navigation:** Likely horizontal, high-contrast text, minimal visual ornamentation.

**Interaction States:**
- Hover/Focus: Likely opacity shifts or subtle darkening of backgrounds.
- Active states: Possibly weight or color shifts (though limited by two-color system).

## 5. Spacing & Layout

**Base Unit:** 2px, enabling fine-grained control.

**Scale:** [2, 4, 8, 12, 16, 22, 58, 72] pixels. This 8-step scale balances granularity with simplicity.
- **Micro (2–4px):** Tight letter-spacing, icon-to-text gaps.
- **Small (8–12px):** Padding within buttons, space between inline elements.
- **Medium (16–22px):** Section padding, gaps between components.
- **Large (58–72px):** Major section breaks, hero spacing.

**Layout Grid:** The 8px interval (and 16px double-unit) suggests an 8px or 16px baseline grid. The single breakpoint at 768px indicates a two-tier responsive strategy:
- **Mobile (<768px):** Single-column, full-width containers, large vertical spacing to accommodate touch.
- **Tablet/Desktop (≥768px):** Multi-column grids, tighter horizontal spacing.

**Rationale:** Spacing increments are large enough to avoid visual clutter, yet small enough to allow nuanced composition. The 58px and 72px values suggest major section separators—fitting for a narrative-heavy marketing site.

## 6. Motion & Interaction

**Timing:**
- **durationFastMs: 100ms** – Micro-interactions (button press feedback, tooltip fade-in, icon swap).
- **durationBaseMs: 200ms** – Standard transitions (page scroll, modal entrance, hover state shift).
- **durationSlowMs: 800ms** – Lengthy animations (hero section reveal, sequential list item fade-in).

**Easing:** cubic-bezier(0.16, 1, 0.3, 1) – A custom ease-out curve biased toward snappy, responsive feel. The early jump (0.16 → 1) and quick settle (0.3 → 1) suggest animations that feel immediate and crisp, not floaty or delayed. Ideal for a research-focused brand where responsiveness signals competence.

**Interaction Patterns:**
- **Buttons:** Likely scale or opacity shift on hover, quick 100–200ms feedback.
- **Links:** Possible underline animation, color or weight shift.
- **Scrolling Sections:** Possible fade-in on scroll, staggered reveals for list items (using 200–800ms durations).

## Accessibility

### Contrast Ratios

**Main pair: #141413 (text) on #faf9f5 (background)**
- Luminance of #141413 ≈ 0.02
- Luminance of #faf9f5 ≈ 0.97
- Contrast ratio ≈ **20.7:1**

This exceeds WCAG AAA (7:1) by a wide margin, ensuring legibility for all users, including those with low vision or color blindness.

**Secondary pair: #ffffff (on-primary) on #141413 (surface)**
- Luminance of #ffffff = 1.0
- Luminance of #141413 ≈ 0.02
- Contrast ratio ≈ **21:1**

Similarly excellent for inverse layouts.

### Minimum Requirements

- **Touch Target Size:** All interactive elements (buttons, links, form inputs) must be at least 44×44px (CSS pixels) to meet WCAG 2.1 Level AAA. Given the compact 12px body text and 58px headings, careful padding/height design is critical; a 12px link in a tight card may require 28–32px of vertical padding to reach the 44px threshold.
- **Focus Indicator:** All keyboard-navigable elements must have a visible focus state—recommend a 2px solid or outline stroke in the primary color (#141413) with a 2px offset, ensuring it's not obscured by shadows or borders. On dark backgrounds, use #ffffff for contrast.
- **Motion:** Users who prefer reduced motion (prefers-reduced-motion media query) should receive instant or near-instant transitions (50–100ms) instead of 200–800ms animations. Ensure no parallax or auto-playing video without pause controls.
