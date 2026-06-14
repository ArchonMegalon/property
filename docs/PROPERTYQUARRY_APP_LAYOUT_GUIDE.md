# PropertyQuarry App Layout Guide

This guide defines the authenticated PropertyQuarry product layout down to component sizing, spacing, typography, state behavior, and page responsibility. It is the implementation reference for redesign work on the app shell, search desk, results, property review, agents, and account surfaces.

The product loop is:

```text
Brief -> Search -> Compare -> Property Review -> Decide -> Follow up -> Learn
```

The UI should never feel like a collection of internal tools. It should feel like a calm property decision desk.

## 1. Product Shape

### 1.1 Primary Surfaces

Use five authenticated surfaces.

| Surface | Purpose | Primary User Question |
| --- | --- | --- |
| Home | Resume work and see what needs attention | What changed and what should I open? |
| Search | Build/edit a brief and watch a live run | What are we looking for and how far along is it? |
| Results | Compare one finished run | Which properties are worth opening? |
| Property | Inspect one property and decide | Would I pursue this property? |
| Agents | Manage recurring market watches | What keeps scanning, what was sent, what was held back? |

Account, billing, profile, settings, notifications, packets, documents, and diagnostics are secondary surfaces. They must be reachable but should not compete with the main workflow in the primary navigation.

### 1.2 Navigation Model

Primary navigation:

```text
Home
Search
Results
Properties
Agents
```

Account menu:

```text
Profile
Billing / Upgrade
Settings
Log out
```

Contextual links:

```text
Review packet
Documents
Map
Listing
Tour
Provider details
```

Diagnostics:

```text
Collapsed by default
Visible only when it directly helps the user recover or understand a search
Operator-level data goes to admin/Teable, not customer pages
```

## 2. Global Layout System

### 2.1 Page Widths

Use fixed responsive containers, not arbitrary full-width panels.

| Context | Width |
| --- | ---: |
| Global app shell max width | `1840px` |
| Comfortable content max width | `1280px` |
| Reading column max width | `760px` |
| Narrow inspector/sidebar | `320px` |
| Wide inspector/sidebar | `420px` |
| Full review split left | `minmax(0, 1fr)` |
| Full review split right | `360px` to `440px` |

Default authenticated page wrapper:

```css
.pq-page {
  width: min(1840px, calc(100vw - 40px));
  margin: 0 auto;
  padding: 20px 0 72px;
}
```

Mobile wrapper:

```css
@media (max-width: 760px) {
  .pq-page {
    width: min(100vw - 24px, 100%);
    padding: 12px 0 72px;
  }
}
```

### 2.2 Breakpoints

Use these breakpoints consistently.

| Breakpoint | Width | Behavior |
| --- | ---: | --- |
| `xs` | `< 480px` | single column, bottom action bar, compact labels |
| `sm` | `480-759px` | single column, 2-up facts where safe |
| `md` | `760-1023px` | single column main content, optional sticky mobile tabs |
| `lg` | `1024-1279px` | two-column content where useful |
| `xl` | `1280-1599px` | full desktop split layouts |
| `xxl` | `>= 1600px` | full app shell with comfortable gutters |

Do not use viewport-scaled font sizes. Use fixed or tokenized sizes.

### 2.3 Grid Rules

Base grid:

```text
4px micro unit
8px component unit
16px block unit
24px section unit
32px page unit
```

Default gaps:

| Scope | Gap |
| --- | ---: |
| icon to label | `6px` |
| chips/buttons in a row | `8px` |
| fields in compact group | `10px` |
| card internal grid | `12px` |
| section internal grid | `16px` |
| page columns | `20px` |
| major page bands | `28px` |

Hard rule: if a card contains more than 3 independent groups, split it into tabs, a wizard, or a collapsed detail section.

### 2.4 Radius And Borders

Cards must be restrained.

| Element | Radius |
| --- | ---: |
| icon button | `8px` |
| input/select | `8px` |
| cards | `8px` |
| modals | `10px` |
| pills/chips | `999px` |
| media thumbnails | `6px` |
| tables | `8px` outer wrapper |

Borders:

```css
border: 1px solid var(--pq-line);
```

Avoid nested cards. A card may contain rows, tables, sections, and details, but not another visual card with its own drop shadow.

### 2.5 Shadow

Use minimal shadows.

```css
--pq-shadow-soft: 0 8px 24px rgba(38, 32, 22, 0.08);
--pq-shadow-panel: 0 14px 36px rgba(38, 32, 22, 0.10);
```

Use shadow only for:

```text
sticky app bars
menus
modals
floating selected-property preview
```

Do not use shadow on every card in a list.

## 3. Typography

### 3.1 Font Stack

Use system fonts first, with Inter if present.

```css
font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
```

No negative letter spacing. Letter spacing defaults to `0`.

### 3.2 Type Scale

| Token | Size | Line Height | Weight | Use |
| --- | ---: | ---: | ---: | --- |
| `display` | `28px` | `34px` | `650` | page title on Home/Search/Property |
| `h1` | `24px` | `30px` | `650` | major page heading |
| `h2` | `18px` | `24px` | `650` | section heading |
| `h3` | `15px` | `20px` | `650` | card title/table property title |
| `body` | `14px` | `21px` | `400` | normal text |
| `body-strong` | `14px` | `21px` | `650` | important row value |
| `small` | `12px` | `16px` | `500` | metadata, helper text |
| `micro` | `11px` | `14px` | `650` | labels, compact metrics |

### 3.3 Text Behavior

Every dynamic text container must protect against overflow.

```css
min-width: 0;
overflow-wrap: anywhere;
```

One-line truncation:

```css
white-space: nowrap;
overflow: hidden;
text-overflow: ellipsis;
```

Two-line truncation:

```css
display: -webkit-box;
-webkit-line-clamp: 2;
-webkit-box-orient: vertical;
overflow: hidden;
```

Never let property titles, provider names, locations, or previous-search names overflow their parent.

## 4. Color System

The app should feel calm and premium, not monochrome.

### 4.1 Core Tokens

```css
--pq-bg: #f6f3ee;
--pq-paper: #fffdf8;
--pq-panel: #fdf9f1;
--pq-ink: #191714;
--pq-muted: #6c675f;
--pq-faint: #958e83;
--pq-line: #ded6c8;
--pq-line-strong: #b9ad9a;
--pq-charcoal: #242321;
--pq-gold: #bd8b2f;
--pq-green: #276b53;
--pq-red: #a65347;
--pq-blue: #315e87;
```

### 4.2 Usage

| Use | Color |
| --- | --- |
| primary action | `--pq-charcoal` |
| selected state | `--pq-charcoal` background, light text |
| positive/confirmed | `--pq-green` |
| warning/unclear | `--pq-gold` |
| blocked/error | `--pq-red` |
| neutral informational | `--pq-blue` |

Do not let beige/cream dominate every visual element. Use charcoal, green, blue, and gold as functional accents.

## 5. Buttons, Links, And Controls

### 5.1 Button Sizes

| Button | Height | Padding | Font |
| --- | ---: | ---: | --- |
| primary desktop | `40px` | `0 14px` | `14px/650` |
| compact | `34px` | `0 10px` | `13px/650` |
| icon-only | `40px` square | none | icon |
| mobile primary | `44px` minimum | `0 14px` | `14px/650` |

Touch target minimum:

```text
44px x 44px on mobile
40px x 40px on desktop
```

### 5.2 Button Semantics

Use one primary button per state.

Examples:

```text
Search brief: Run search
Live run: Refresh
Results: Open selected
Property: Save decision
Agent detail: Run now
Account: Upgrade
```

Secondary actions:

```text
Edit
Duplicate
Map
Listing
Pause
Reset
```

Destructive actions:

```text
Delete
Archive
Hide
```

Destructive buttons should not be primary-styled. Use restrained text/button style with confirmation if irreversible.

### 5.3 Clickability Rule

Anything that looks clickable must respond predictably.

Clickable:

```text
button
link
card with hover and clear action
table row if it selects or opens
chip if it toggles
```

Not clickable:

```text
static badge
metric
status label
plain row
```

Static badges must not have hover cursor, border glow, or button-like depth.

## 6. Forms

### 6.1 Search Brief Form

The brief form should be a guided form, not one long dashboard.

Desktop layout:

```text
Left: essentials form, max 760px
Right: saved searches / brief summary, 360-420px
```

Mobile layout:

```text
Single column
Sticky bottom action: Run search
Advanced filters collapsed
```

Field dimensions:

| Field | Width |
| --- | ---: |
| country/mode/type select | `minmax(180px, 1fr)` |
| provider group selector | full width |
| price/area/rooms inputs | `minmax(120px, 1fr)` |
| location input | full width |
| slider | full width, min `220px` |

Input height:

```text
40px desktop
44px mobile
```

### 6.2 Form Sections

Search essentials, always visible:

```text
Country
Area
Mode
Property type
Budget if user set one
Provider groups
Result mode: Strict shortlist / Discovery pass
Run button
```

Advanced filters, collapsed by default:

```text
school distance
supermarket distance
entertainment radius
commute caps
floorplan requirement
tour requirement
investment filters
developer/cooperative sources
```

Never show an unset budget suggestion as if the user entered a budget.

### 6.3 Saved Search Edit State

When loading a saved search into the form, show:

```text
Loaded: Vienna rent watch
Unsaved changes: 3 fields
[Run with these filters] [Save changes] [Save as new] [Reset]
```

Do not call this "Load filters" in UI. Use `Edit`.

## 7. Page Designs

## 7.1 Home

Purpose: resume work.

Desktop layout:

```text
Header: "PropertyQuarry"
Subheader: next useful summary

Main grid:
  left 2/3: Previous searches
  right 1/3: Next actions
```

Pixel layout:

```text
page max width: 1280px
grid columns: minmax(0, 1fr) 360px
gap: 20px
cards: 8px radius
run card height: 112-148px
```

Previous search card content:

```text
name
last run
status
best fit
new since last run
sent / held back
Open results button
```

Do not show the full search form on Home unless there are no previous searches and no saved agents.

Empty Home state:

```text
Choose a starting point:
[Evaluate one listing] [Create recurring search] [Run market scan]
```

## 7.2 Search

Search has three mutually exclusive states:

```text
brief_builder
run_in_progress
finished_summary
```

### Brief Builder

Header:

```text
New search
Tell us what to find.
```

Body:

```text
Essentials form
Saved searches / brief summary
```

Do not show previous-search results above the form on the Search page. Previous searches belong on Home or Results.

### Run In Progress

The live run panel should fit in the first viewport.

Show only:

```text
42% | about 6 min
5 / 12 sources checked
Current source/action
compact source chips
optional small AvoMap strip if route filters are active
```

Do not show:

```text
four-stage animated labels
duplicate progress rings
large diagnostics
provider repair forms
full event log
large graphics
```

Diagnostics go in a collapsed details block:

```text
Search details
Source events
Held back by rules
Provider warnings
```

Progress card dimensions:

```text
max width: 760px
padding: 14px desktop, 12px mobile
gap: 10px
progress bar height: 8px
source chip height: 28px
route strip card max height: 96px
```

### Finished Summary

When a run finishes, do not keep the progress panel as the main thing.

Show:

```text
Run complete
Best matches ready
[Open results]
```

Then a compact run summary:

```text
sources checked
listings seen
ranked
sent
held back
```

## 7.3 Results

Purpose: compare properties.

Primary layout:

```text
Left: ranked table/list
Right: selected preview
```

Desktop:

```text
grid columns: minmax(0, 1fr) 380px
gap: 18px
```

Mobile:

```text
ranked list first
selected preview opens as sheet or below selected row
```

Table columns:

| Column | Width |
| --- | ---: |
| rank | `48px` |
| property | `minmax(260px, 1fr)` |
| fit | `72px` |
| reason | `minmax(260px, .9fr)` |
| route | `150px` |
| actions | `160px` |

Row height:

```text
72px normal
96px with thumbnail
```

The result row should show:

```text
title
source
location
fit score
top reason
top risk/unknown if important
Review / Map actions
```

Do not put the decision wizard in Results. Results are for comparison.

Held-back summary:

```text
collapsed by default after the ranked table
show counts by reason
each reason has one action
```

Examples:

```text
Missing floorplan - 18 held back - Run floorplan recovery
Below fit threshold - 11 held back - Show near misses
Notification budget - 7 held back - Increase budget
```

## 7.4 Property Review

Purpose: inspect one property and decide.

Desktop layout:

```text
Top: property header
Main: media/facts left, decision panel right
Below: tabbed evidence
```

Grid:

```text
main columns: minmax(0, 1fr) 380px
gap: 20px
decision panel sticky top: 84px
```

Mobile:

```text
property header
media
decision wizard
tabs
```

### Property Header

Height:

```text
96-140px desktop
auto mobile
```

Content:

```text
title
source
location
fit score
price / area / rooms
actions: Review, Map, Listing, Tour
```

Map links must point to the best available exact address or coordinates, not just district. If exact location is unavailable, label it clearly:

```text
Map area
```

not:

```text
Map
```

### Media

Media block:

```text
aspect ratio: 16 / 9
min height desktop: 320px
max height desktop: 560px
mobile width: 100%
```

If no 360/tour exists:

```text
show a quiet unavailable state
show next action if useful
do not show internal export failure codes
```

### Decision Wizard

The decision wizard belongs on the Property page only.

Initial state:

```text
Would you pursue this property?
[Yes] [Maybe] [No] [Hide]
```

Dimensions:

```text
panel width desktop: 360-420px
padding: 14px
button height: 40px
row gap: 8px
```

After answer:

```text
Why?
reason chips
agent question preview
consequence preview
note
[Save decision]
```

Advanced actions collapsed:

```text
Viewing requested
Documents requested
Offer candidate
Archived
```

The wizard must not expose all steps at once. Show:

```text
Step 1: answer
Step 2: explain
Step 3: save
```

Behavior:

```text
Selecting answer reveals reasons.
Selecting No prioritizes negative reasons.
Selecting Maybe prioritizes missing facts/documents.
Selecting Yes prioritizes next real-world actions.
Save writes durable decision ledger.
After save, show what changed.
```

Post-save result:

```text
Decision saved.
Created:
- agent question
- document request
- future ranking update
```

### Evidence Tabs

Use tabs instead of stacked cards.

Tabs:

```text
Overview
Risks
Daily life
Documents
Timeline
```

Tab bar:

```text
height: 44px
button min width: 96px
horizontal scroll on mobile
```

Do not show all evidence categories as full stacked sections at once.

## 7.5 Agents

Rename visually to:

```text
Market watch
```

Page layout:

```text
Top: active/paused/sent/held-back metrics
Main: agent list
Right or lower: selected agent details
```

Agent card height:

```text
112-156px
```

Agent card content:

```text
name
status
market scope
cadence
message budget
last run
next run
sent / held back
Open / Edit / Run now
```

Agent detail:

```text
summary
run history
what changed
suppression reasons
notification budget
learning applied
actions
```

Do not let agent management look like a settings table. It is a market watchlist.

## 7.6 Account

Account menu is always in the top-right.

Menu width:

```text
220-260px
```

Menu items:

```text
Upgrade
Profile
Settings
Log out
```

Billing page:

```text
current plan
usage
available upgrades
payment status
```

Upgrade CTA should be visible in the account menu and on plan-limit states.

## 8. Components

### 8.1 Cards

Default card:

```css
.pq-card {
  border: 1px solid var(--pq-line);
  border-radius: 8px;
  background: var(--pq-paper);
  padding: 14px;
}
```

Card header:

```text
title left
status/action right
gap 10px
```

Never use a card only to decorate a section. Cards are for repeated items, selected panels, modals, and specific tools.

### 8.2 Tables

Tables are preferred for comparing results.

Table wrapper:

```css
overflow-x: auto;
border: 1px solid var(--pq-line);
border-radius: 8px;
```

Headers:

```text
12px uppercase
muted
height 36px
```

Cells:

```text
14px body
padding 10px 12px
vertical-align middle
```

Rows:

```text
border-bottom 1px solid line
hover only if row is clickable/selectable
selected row has left accent or subtle background
```

### 8.3 Pills And Chips

Use chips sparingly.

Max visible chips per area:

```text
decision reasons: 8
source chips: 8
filters summary: 6
provider groups: 10
```

Overflow behavior:

```text
+N more
or collapse into details
```

### 8.4 Empty States

Every empty state must answer:

```text
why empty
what to do next
what happens after click
```

Examples:

```text
No strong matches yet.
Run a discovery pass to keep this location and rank softer lifestyle misses instead of filtering them out.
[Run discovery pass]
```

```text
No saved searches yet.
Create a market watch when this brief should keep running.
[Create saved search]
```

### 8.5 Failure States

Failure display:

```text
human message
retry action
fallback action
operator detail collapsed
```

Never show raw backend codes in primary text.

## 9. Motion And Progress

Motion should clarify state, not decorate.

Allowed:

```text
progress bar width transition
subtle active source pulse
route line drawing in small AvoMap preview
toast fade
menu open/close
```

Avoid:

```text
multiple simultaneous animations
large decorative graphics
spinners without progress
fake progress jumps
```

Progress behavior:

```text
show percentage 0-100
show ETA
show sources checked
show current activity
```

Progress formula should be based on real source/candidate stages where possible. If estimate is fallback, label remains calm:

```text
12% | estimating
42% | about 6 min
100% | complete
```

## 10. AvoMap Route Previews

AvoMap belongs in three places:

```text
Search progress: compact preview strip while route-relevant filters are active
Results: one route evidence column
Property: Daily life tab / route section
```

Compact progress preview:

```text
max 3 cards
height 76-96px
show label, destination, mode/time
click opens directions from property to destination
```

Priority:

```text
1. user custom navigation filter
2. school/kindergarten if family mode
3. supermarket
4. transit
```

If property coordinates/address are unknown, do not render a route preview. Show route evidence later when available.

## 11. Responsive Behavior

### 11.1 Mobile

Mobile primary pattern:

```text
top app bar
single column content
sticky bottom primary action for forms/wizards
horizontal tabs for evidence
details collapsed by default
```

Do not show desktop sidebars on mobile.

### 11.2 Tablet

Tablet pattern:

```text
single column for Search and Property
two-column for Results only if width >= 900px
account menu top-right
```

### 11.3 Desktop

Desktop pattern:

```text
Home: dashboard + next actions
Search: brief + summary
Results: table + selected preview
Property: media/evidence + sticky decision
Agents: list + selected detail
```

## 12. Accessibility

Required:

```text
visible focus state
button labels are meaningful
target size >= 44px on mobile
color not sole state indicator
menus usable by keyboard
details/summary labels are meaningful
tables have headers
forms have labels
```

Focus ring:

```css
outline: 3px solid rgba(189, 139, 47, 0.34);
outline-offset: 2px;
```

## 13. Copy Rules

Tone:

```text
premium
calm
analytical
direct
```

Use:

```text
Confirmed
Likely
Unclear
Missing
Needs owner review
Provider-only
Official-source backed
```

Avoid:

```text
EA
OODA
artifact
hosted review
raw backend codes
raw URLs as visible labels
internal provider repair language
```

Customer-facing text should describe impact:

```text
This provider did not return details yet.
```

not:

```text
provider_extract_failed
```

## 14. Visual QA Gates

Every redesign slice must pass:

```text
no horizontal overflow at 390px, 768px, 1440px
no text escaping cards
no duplicate progress graphics
no raw URLs as labels
no internal jargon
first viewport contains the primary action
running progress fits in one screen
decision wizard starts collapsed to one simple question
```

Screenshots to capture:

```text
Home desktop/mobile
Search brief desktop/mobile
Live run desktop/mobile
Results desktop/mobile
Property review desktop/mobile
Agents desktop/mobile
Account menu open desktop/mobile
```

## 15. Implementation Migration Order

Recommended order:

1. Stabilize app shell and account menu.
2. Split Home from Search.
3. Reduce live progress to percent, ETA, source status, and compact route previews.
4. Move decision wizard out of results/listing rows and into Property review.
5. Convert Property evidence to tabs.
6. Convert Agents to Market watch cockpit.
7. Add screenshot gates for each major state.

## 16. Non-Negotiable Rules

```text
No decision wizard inside result cards.
No full search form on returning-user Home.
No raw URLs as visible text.
No internal jargon on customer surfaces.
No duplicate progress widgets.
No card walls where a table or tabs are clearer.
No clickable-looking static elements.
No text overflow.
No fake 360/tour labels.
No location map link unless it points to the best available exact location; otherwise label it as area map.
```

This guide is the UI contract for PropertyQuarry. Product changes can add capability, but they should not add visual weight unless they improve compare, decide, or act.
