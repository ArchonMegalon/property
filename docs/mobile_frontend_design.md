# Mobile Frontend Design

## Decision

PropertyQuarry should stay a single product with a responsive frontend, not a separate mobile-only application.

Reason:
- the main workflows are the same on desktop and mobile
- the product already has shared shells and shared state
- the current problem is layout discipline, not missing mobile-specific product concepts

## Product goals

Mobile should feel:
- minimal
- fast to scan
- one-task-at-a-time
- credible for serious property work

It should not feel like:
- a compressed desktop UI
- a hidden operator console
- a second-class fallback surface

## Surface model

### Public surfaces

Mobile public pages should use:
- one-column layout
- compact sticky header
- visible mobile nav row
- full-width primary CTAs
- no side-by-side hero or pricing density on phone widths

Primary public pages:
- Home
- Pricing
- Sign in
- Guides / editorial pages

### App surfaces

Mobile app pages should use:
- one active panel at a time
- bottom navigation for core surfaces
- stacked actions
- compact evidence blocks
- no right rail dependence

Primary app surfaces:
- Search brief
- Results shortlist
- Property detail
- Saved searches
- Account

## Breakpoints

- `>= 1080px`: desktop
- `760px - 1079px`: tablet / compact desktop
- `<= 759px`: phone
- `<= 520px`: narrow phone

## Layout rules

### Shared shell

- page gutters shrink from desktop spacing to `10px - 14px` on phone
- headers become vertical stacks on phone
- hidden desktop nav must be replaced with a visible mobile nav, not removed
- tap targets stay at least `40px`

### Public header

- brand row stays visible
- nav becomes a horizontal scroll row below the brand/actions row
- action buttons become full-width or balanced half-width buttons on phone

### Workbench

- results, brief, and property review are separate mobile panels
- results cards become fully stacked
- media sits above text, not beside it, on narrow widths
- property actions become one-column controls
- optional context stays collapsed by default

### Property detail

- hero media stays first
- decision stack follows immediately
- map, gallery, and evidence blocks stack cleanly
- tables and split grids collapse to one column

## Content rules

- use short status labels
- remove duplicate explanatory text on phone
- prefer one strong CTA over multiple equal-weight actions
- keep evidence visible, but secondary

## Visual rules

- preserve existing visual language
- reduce panel padding on phone
- keep rounded corners restrained
- avoid card-in-card density
- avoid horizontal overflow

## Implementation order

1. shared public shell
2. shared app shell
3. public home / pricing / sign-in
4. shortlist / selected property panel
5. property detail page
6. remaining secondary surfaces

## Acceptance bar

Mobile is acceptable when:
- no page horizontally overflows on a `390px` viewport
- public navigation remains usable without the desktop nav
- shortlist cards and property actions are readable with one hand
- property detail does not depend on a hidden right rail
- the product still feels like the same product, not a degraded mode
