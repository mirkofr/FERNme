# FERNme SPA Design System and Graph UI Specification

**Version:** 2.0
**Frontend:** Vite + React + TypeScript
**Source application:** `fernme/web/app`
**Generated bundle:** `fernme/web/static/app`
**Primary route:** `/ui/graph`
**Design direction:** elegant, futuristic, icon-led, inspectable user-owned memory graph

---

## 1. Migration-aware implementation rule

FERNme is now a React SPA. The old `graph.html` and `glassbox.html` implementation no longer exists and must not be recreated.

All design work belongs in the **source SPA**:

```text
fernme/web/app/
```

The generated bundle is deployment output:

```text
fernme/web/static/app/
```

Never hand-edit files inside `fernme/web/static/app`. The bundle must be regenerated through the existing Vite build command.

The backend routing contract is:

```text
/ui             -> SPA
/ui/*           -> SPA history fallback
/graph          -> redirect to /ui/graph
```

The design must preserve:

- local-only runtime assets;
- no CDN dependency;
- scroll-safe and collapsible filters;
- canonical entity-kind filtering;
- REST-backed Graph, Review queue, Memory editor, Feed, Health, and recall replay;
- packaged static build compatibility.

---

## 2. Required source file placement

Place the four design files in the SPA source tree:

```text
fernme/web/app/src/
â”œâ”€â”€ design/
â”‚   â””â”€â”€ token.json
â””â”€â”€ styles/
    â”œâ”€â”€ variables.css
    â””â”€â”€ theme.css
```

Keep this specification in either:

```text
docs/ui-design.md
```

or:

```text
fernme/web/app/design.md
```

Import the CSS once in `src/main.tsx`, in this order:

```tsx
import "./styles/variables.css";
import "./styles/theme.css";
```

Do not import `theme.css` independently from route components. The shell and all routes share one visual system.

---

## 3. Suggested React architecture

Use feature-oriented components rather than one large page component.

```text
src/
â”œâ”€â”€ app/
â”‚   â”œâ”€â”€ App.tsx
â”‚   â”œâ”€â”€ router.tsx
â”‚   â””â”€â”€ providers.tsx
â”œâ”€â”€ layout/
â”‚   â”œâ”€â”€ AppShell.tsx
â”‚   â”œâ”€â”€ TopBar.tsx
â”‚   â”œâ”€â”€ PrimaryNavigation.tsx
â”‚   â””â”€â”€ ContextControls.tsx
â”œâ”€â”€ features/
â”‚   â”œâ”€â”€ graph/
â”‚   â”‚   â”œâ”€â”€ GraphPage.tsx
â”‚   â”‚   â”œâ”€â”€ GraphCanvas.tsx
â”‚   â”‚   â”œâ”€â”€ GraphToolbar.tsx
â”‚   â”‚   â”œâ”€â”€ FilterRail.tsx
â”‚   â”‚   â”œâ”€â”€ GraphInsights.tsx
â”‚   â”‚   â”œâ”€â”€ EntityInspector.tsx
â”‚   â”‚   â”œâ”€â”€ GraphLegend.tsx
â”‚   â”‚   â”œâ”€â”€ graph-icons.ts
â”‚   â”‚   â”œâ”€â”€ graph-renderer.ts
â”‚   â”‚   â”œâ”€â”€ graph-layout.ts
â”‚   â”‚   â”œâ”€â”€ graph-animation.ts
â”‚   â”‚   â””â”€â”€ graph.types.ts
â”‚   â”œâ”€â”€ review/
â”‚   â”œâ”€â”€ memory/
â”‚   â”œâ”€â”€ feed/
â”‚   â”œâ”€â”€ health/
â”‚   â””â”€â”€ recall/
â”œâ”€â”€ shared/
â”‚   â”œâ”€â”€ api/
â”‚   â”œâ”€â”€ components/
â”‚   â”œâ”€â”€ hooks/
â”‚   â””â”€â”€ utils/
â”œâ”€â”€ design/
â”‚   â””â”€â”€ token.json
â””â”€â”€ styles/
    â”œâ”€â”€ variables.css
    â””â”€â”€ theme.css
```

The exact project structure may differ, but these boundaries should remain:

- React controls layout, filters, inspector, routing, REST state, and accessibility.
- The graph renderer controls canvas drawing and animation.
- D3 may control forces, zoom, and spatial calculations.
- The renderer must not create or mutate application DOM nodes.
- Route components must not contain large inline style objects.

---

## 4. Route-level shell

All primary views share one shell:

```tsx
<AppShell>
  <Outlet />
</AppShell>
```

Routes:

```text
/ui/graph
/ui/review
/ui/memory
/ui/feed
/ui/health
/ui/recall
```

Navigation labels remain:

- Graph
- Review queue
- Memory editor
- Feed
- Health

Use `NavLink` or the router's equivalent. The active state must come from the current route, not local component state.

The route transition should not animate the entire page. Only use a short opacity transition for the route content when appropriate.

---

## 5. Product intent

The Graph page is a **living, inspectable memory map**, not a generic analytics dashboard.

It must communicate:

1. The user owns and controls the graph.
2. Different entity kinds are immediately recognizable.
3. Relationships appear active and meaningful.
4. Memories and relations can be inspected, reviewed, edited, and deleted.
5. Proposed information is visually distinct from accepted memory truth.

The interface should feel advanced but calm:

- precise spacing;
- restrained glow;
- subtle motion;
- strong typography;
- no decorative AI imagery;
- no fake intelligence labels;
- no unnecessary glass cards.

---

## 6. Visual principles

### 6.1 Premium, not noisy

Use:

- midnight navy rather than pure black;
- one thin border per panel;
- one restrained shadow layer;
- glow only for active graph entities and live states;
- a single subtle canvas vignette;
- minimal gradients.

Do not:

- put every element inside a glowing box;
- use bright outlines on all controls;
- animate all links;
- use floating decorative orbs;
- use emoji in graph nodes.

### 6.2 Dense, not cramped

Maintain:

- 12â€“16 px card padding;
- 8 px between related controls;
- 14â€“20 px between sections;
- minimum 36 px control height;
- minimum 24 px clear space around major graph anchors.

### 6.3 Semantic color

Color identifies entity kind.

| Kind | Token | Local icon |
|---|---|---|
| Owner/user | `graph-owner` | `UserRoundCheck` |
| Person | `graph-person` | `UserRound` |
| Organization | `graph-organization` | `Building2` |
| Project | `graph-project` | `BriefcaseBusiness` |
| Concept/topic | `graph-concept` | `Sparkles` or `Lightbulb` |
| Place | `graph-place` | `MapPin` |
| Event/milestone | `graph-event` | `CalendarDays` or `Star` |
| Fact | `graph-fact` | `FileText` |
| Habit | `graph-habit` | `Repeat2` |
| Knowledge | `graph-knowledge` | `BrainCircuit` |
| Value | `graph-value` | `ShieldCheck` |
| Proposed | `graph-proposed` | `WandSparkles` |

For graph nodes, canonical entity kind determines the principal color and icon. Category may appear as a small secondary marker or inspector metadata.

---

## 7. Local icon rule

Use a locally installed icon library, preferably `lucide-react`.

Example:

```tsx
import {
  BrainCircuit,
  BriefcaseBusiness,
  Building2,
  CalendarDays,
  FileText,
  Lightbulb,
  MapPin,
  Repeat2,
  ShieldCheck,
  Sparkles,
  Star,
  UserRound,
  UserRoundCheck,
} from "lucide-react";
```

The package must be bundled by Vite. Do not load icon scripts or SVGs from a CDN.

For canvas rendering, React icons cannot be drawn directly on the canvas. Create a local icon cache:

1. map canonical entity kinds to SVG path data;
2. render SVG to an offscreen canvas;
3. cache by `kind`, semantic color, pixel size, and DPR;
4. draw cached bitmaps in the main canvas render loop.

Alternative: implement simple vector glyphs with `Path2D`.

Do not use mixed icon families.

---

## 8. Desktop geometry

Baseline design target: **1440 Ã— 900**.

```text
Top bar:            72 px
Left filter rail:   276 px
Right insight rail: 252 px
Workspace gap:      14 px
Graph toolbar:      58 px
Panel radius:       12 px
Control radius:      9 px
```

Grid:

```text
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚ TopBar                                                           â”‚
â”œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¤
â”‚ FilterRail    â”‚ GraphToolbar + GraphCanvas       â”‚ GraphInsights  â”‚
â”‚ 276 px        â”‚ fluid                            â”‚ 252 px          â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

The graph is the dominant surface. Combined side rails must not consume over 40% of viewport width.

---

## 9. React class contract

Use these stable class names. Components may add CSS-module classes, but these global classes define the approved design.

```text
fern-app
topbar
brand
brand__mark
brand__name
primary-nav
primary-nav__item
topbar__context
workspace
filter-rail
graph-workspace
graph-toolbar
graph-stage
insight-rail
panel
filter-card
filter-list
filter-row
summary-card
insight-card
legend-card
graph-status
graph-realtime
graph-zoom
graph-tooltip
inspector
```

Example:

```tsx
export function GraphPage() {
  return (
    <div className="workspace graph-route">
      <FilterRail />

      <section className="graph-workspace" aria-label="Memory graph">
        <GraphToolbar />
        <GraphCanvas />
      </section>

      <GraphInsights />
    </div>
  );
}
```

The workspace should be owned either by `GraphPage` or by a graph-specific nested layout. Do not make non-graph routes render empty graph side rails.

---

## 10. Top bar

### Brand

- mark: 28â€“30 px;
- wordmark: 21 px, weight 700;
- use owner green for the fern;
- no glowing circular background.

### Navigation

- active route: soft green-tinted surface and 2 px underline;
- inactive text: muted;
- hover: only text and surface;
- no scale or bounce animation.

### Context controls

Controls:

- personal scope;
- current user;
- context attributes;
- Load.

Each selector:

- 38 px height;
- local leading icon;
- trailing chevron;
- 1 px border;
- minimum width 142 px on wide screens.

`Load` is the only solid primary action in the top bar.

---

## 11. Left filter rail

Sections:

1. Categories
2. Entity kinds
3. Saved filters

Use buttons for rows:

```tsx
<button
  type="button"
  className="filter-row filter-row--person"
  aria-pressed={selected}
>
  <span className="filter-row__icon">...</span>
  <span className="filter-row__label">Person</span>
  <span className="filter-row__count">152</span>
</button>
```

Rows are full-width, not floating pills.

Dimensions:

- row height: 38 px;
- icon tile: 24 Ã— 24 px;
- icon: 14 px;
- count badge: at least 34 Ã— 22 px;
- vertical gap: 4 px.

State rules:

- default: transparent;
- hover: neutral raised surface;
- selected: low-opacity semantic fill and semantic border;
- focus: owner-green focus ring;
- disabled: 45% opacity.

The filter rail itself scrolls independently. It must never make the graph page vertically overflow.

Canonical kind handling must come from the shared entity-kind model. Do not duplicate ad-hoc kind aliases in the UI.

---

## 12. Graph toolbar

Contents:

- Search memory graph;
- Focus;
- Fit;
- Known only;
- optional layout selector;
- optional Insights button on narrow screens.

Dimensions:

- height: 58 px;
- search max width: 420 px;
- control height: 36 px;
- gap: 8 px.

`Known only` uses an accessible switch:

```tsx
<button
  type="button"
  className="switch-control"
  role="switch"
  aria-checked={knownOnly}
  onClick={toggleKnownOnly}
>
  <span className="switch" aria-hidden="true" />
  Known only
</button>
```

---

## 13. Graph canvas component

Recommended component boundary:

```tsx
<GraphCanvas
  graph={visibleGraph}
  selectedNodeId={selectedNodeId}
  focusedNodeId={focusedNodeId}
  reducedMotion={reducedMotion}
  onSelectNode={setSelectedNodeId}
  onSelectEdge={setSelectedEdgeId}
/>
```

`GraphCanvas` owns:

- canvas ref;
- resize observer;
- D3 force simulation;
- zoom transform;
- pointer hit testing;
- icon bitmap cache;
- animation frame;
- draw loop.

It must clean up all resources on unmount:

```tsx
useEffect(() => {
  const controller = new AbortController();
  const simulation = createSimulation(...);
  let frameId = requestAnimationFrame(draw);

  return () => {
    controller.abort();
    simulation.stop();
    cancelAnimationFrame(frameId);
  };
}, [graphKey]);
```

Use `ResizeObserver`, not window size alone.

Cap device pixel ratio:

```ts
const dpr = Math.min(window.devicePixelRatio || 1, 2);
```

---

## 14. Canvas background

The graph stage uses CSS background layers beneath a transparent canvas:

```css
background:
  radial-gradient(circle at 52% 44%, rgba(45, 229, 182, 0.035), transparent 42%),
  radial-gradient(circle, rgba(160, 186, 214, 0.13) 1px, transparent 1px),
  #06101a;
background-size: auto, 24px 24px, auto;
```

Do not redraw the grid on every canvas frame.

---

## 15. Graph layout

Use a hybrid force layout.

Recommended starting parameters:

```ts
d3.forceManyBody<GraphNode>()
  .strength(node => node.anchor ? -620 : -110)
  .distanceMax(520);

d3.forceLink<GraphNode, GraphEdge>()
  .id(node => node.id)
  .distance(edge => edge.cross ? 260 : edge.aggregated ? 170 : 92)
  .strength(edge => edge.cross ? 0.12 : 0.34);

d3.forceCollide<GraphNode>()
  .radius(node => node.radius + (node.anchor ? 34 : 18))
  .iterations(2);
```

Requirements:

- major anchors separate into readable communities;
- children orbit or cluster around their anchor;
- cross-community links are longer;
- disconnected nodes remain low emphasis near the outer region;
- initial labels fade in only after the simulation cools;
- saved/returned positions should be reused where available to reduce visual jumping.

Do not randomize all positions on every filter update. Preserve existing node coordinates by ID.

---

## 16. Node sizing and anatomy

| Node role | Radius |
|---|---:|
| owner or selected anchor | 30 px |
| anchor | 24 px |
| normal entity | 15 px |
| fact or attribute | 11 px |
| metadata satellite | 3 px |

Node rendering order:

1. selection/interaction halo;
2. semantic glow;
3. tinted dark body;
4. 1 px semantic border;
5. icon;
6. label.

Owner:

- 30 px body;
- 48 px inner halo;
- 72 px outer halo;
- subtle pulsing highlight;
- 16 px semibold label.

Normal nodes do not have permanent large halos.

---

## 17. Labels

Visibility:

- anchors: always;
- selected neighbors: always;
- normal labels: zoom â‰¥ 0.72;
- low-priority labels: zoom â‰¥ 1.05 or hover;
- disconnected labels: hover only.

Typography:

- normal: 12 px;
- selected neighbor: 13 px;
- owner: 16 px / 600.

Use dark text shadow or a small dark backing behind labels where links cross.

Do not draw every label at low zoom.

---

## 18. Animated connections

The screenshot concept implies animated links. Implement them in the canvas renderer, not with React state updates per frame.

### Static edges

Default:

- width: 1 px;
- alpha: 0.20.

Important:

- width: 1.5 px;
- alpha: 0.46.

Selected adjacency:

- width: 2 px;
- alpha: 0.72;
- small glow.

### Moving particles

Animate only:

- selected-node edges;
- hovered edge;
- newly created relations;
- newly strengthened relations;
- up to 80 prioritized visible edges.

Algorithm:

```ts
const seconds = performance.now() / 1000;
const phase = (seconds / duration + stableOffset) % 1;
const eased = 0.5 - Math.cos(Math.PI * phase) / 2;
const point = pointAlongEdge(edge, eased);
drawGlowParticle(ctx, point, edgeColor);
```

Particle:

- radius: 1.6 px;
- glow: 5 px;
- duration: 1.8â€“3.2 seconds;
- stable offset derived from edge ID.

### Animated dashes

Use only for cross-community, proposed, or currently active relations:

```ts
ctx.setLineDash([2, 8]);
ctx.lineDashOffset = -(timeMs * 0.012 + stableHash(edge.id) % 40);
```

Do not combine strong particles and strong dashes on all edges.

### React performance rule

The draw loop must read current interaction values from refs:

```ts
const interactionRef = useRef({ selectedNodeId, hoveredEdgeId });

useEffect(() => {
  interactionRef.current = { selectedNodeId, hoveredEdgeId };
}, [selectedNodeId, hoveredEdgeId]);
```

Do not call `setState` on every animation frame.

---

## 19. Right insight rail

Cards:

1. visible graph summary;
2. graph insights;
3. legend.

Summary fields:

```text
Visible nodes
181
of 4,218

Visible links
425
of 12,894
```

Insights must be computed from current graph data. Suitable metrics:

- communities detected;
- highest degree entity;
- most connected project;
- sparse graph percentage;
- pending review suggestions affecting visible entities.

Never fabricate insight text.

Below 1180 px, the rail becomes a controlled drawer.

---

## 20. Entity inspector

Open the inspector when a node or edge is selected.

Desktop width: 360 px.
Small screen width: up to 92vw.

Sections:

- entity name and canonical kind;
- aliases;
- fields;
- relations;
- evidence;
- provenance;
- proposed/accepted state;
- edit/delete actions.

The drawer overlays the graph. It must not permanently shrink the canvas.

Actions should use existing REST-backed mutations and invalidate only the relevant query cache.

---

## 21. SPA data-state requirements

Every route must handle:

- initial loading;
- refetching;
- empty data;
- API error;
- unauthorized or missing context;
- mutation pending;
- mutation success;
- mutation failure.

Use stable state containers:

```text
route query state
filter state
graph viewport state
selected entity state
drawer state
```

Do not mix API response state with canvas simulation objects.

Recommended separation:

```ts
type GraphApiNode = ...
type GraphApiEdge = ...

type GraphRenderNode = GraphApiNode & {
  x: number;
  y: number;
  vx: number;
  vy: number;
  radius: number;
};
```

The renderer may mutate render positions. It must not mutate cached REST entities.

---

## 22. Responsive behavior

### 1180â€“1399 px

- left rail: 248 px;
- right rail: 228 px;
- hide low-value filter counts if needed;
- reduce context selector width.

### 900â€“1179 px

- right rail becomes an Insights drawer;
- left rail stays 240 px;
- context selectors collapse into one menu;
- graph remains the primary width.

### Below 900 px

- filter rail becomes an off-canvas drawer;
- graph occupies full width;
- toolbar wraps;
- summary becomes compact overlays;
- do not squeeze the three-column desktop layout.

### Below 600 px

- brand wordmark may collapse to the mark;
- active route remains visible;
- zoom controls span the bottom;
- live status moves above zoom controls.

---

## 23. Accessibility

Required:

- semantic buttons and inputs;
- visible focus rings;
- `aria-current="page"` for route navigation;
- `aria-pressed` for filter toggles;
- `role="switch"` for Known only;
- `aria-live="polite"` for load and sync messages;
- icons paired with text or accessible names;
- normal text contrast â‰¥ 4.5:1;
- colors reinforced by icons;
- inspector accessible without pointer input.

Canvas accessibility:

- render a visually hidden DOM list of visible nodes;
- each item is a button;
- selecting an item focuses and selects the node;
- announce node label, canonical kind, and neighbor count;
- keyboard users must be able to inspect the same information as pointer users.

---

## 24. Reduced motion

Use:

```ts
const reducedMotion = window.matchMedia(
  "(prefers-reduced-motion: reduce)"
).matches;
```

When enabled:

- stop edge particles;
- stop dash movement;
- stop continuous node pulse;
- keep static selection halos;
- keep direct user-triggered focus transitions short and non-bouncy.

The CSS file also disables nonessential transitions.

---

## 25. Performance targets

For approximately 181 nodes and 425 links:

- 60 fps target during idle animation;
- at least 40 fps while dragging;
- DPR capped at 2;
- one `requestAnimationFrame` loop;
- cached icon rasterization;
- cached text measurement;
- no React rerender per animation frame;
- stop rendering while `document.hidden`;
- resume cleanly on visibility change.

Above 1,000 visible nodes:

- hide non-anchor icons below zoom 0.8;
- hide normal labels;
- animate only selected adjacency;
- simplify shadows;
- reduce edge alpha;
- optionally switch to spatial bucketing for hit testing.

---

## 26. Build and packaging workflow

Edit only the SPA source:

```text
fernme/web/app
```

Then run the repository's existing frontend build command:

```bash
npm run build
```

Verify that the configured Vite output is:

```text
fernme/web/static/app
```

Do not change the output path without also updating packaging tests and backend static serving.

Required verification:

```bash
npm run build
python -m pytest tests/test_graph.py tests/test_ui_launcher.py -q
python -m pytest tests/test_mcp_packaging.py -q
python -m pytest -q
```

Also verify manually:

- `/ui`;
- `/ui/graph`;
- direct reload on `/ui/review`;
- `/graph` redirect;
- no CDN requests;
- packaged wheel/sdist contains the SPA bundle;
- browser console has no asset-path or source-map errors.

---

## 27. Implementation sequence for Codex or Claude Cowork

### Phase 1 â€” tokens and shell

1. Copy `token.json` to `src/design/token.json`.
2. Copy `variables.css` and `theme.css` to `src/styles`.
3. Import both once from `src/main.tsx`.
4. Apply `fern-app`, `topbar`, and route shell classes.
5. Implement active navigation with the router.
6. Do not touch generated static files.

### Phase 2 â€” Graph page composition

1. Split `GraphPage` into toolbar, filter rail, canvas, insights, and inspector.
2. Move old renderer behavior into dedicated TypeScript modules.
3. Preserve REST contracts and canonical kind filtering.
4. Preserve node coordinates across filter changes.
5. Add local icons.

### Phase 3 â€” graph rendering

1. Add semantic node body and icon renderer.
2. Add owner and selection halos.
3. Add label zoom thresholds.
4. Add semantic edges.
5. Add prioritized particles and moving dashes.
6. Add reduced-motion behavior.

### Phase 4 â€” responsive and accessible behavior

1. Add filter and insight drawers.
2. Add accessible node list.
3. Add keyboard selection.
4. Add loading, empty, and error states.
5. Run all build, packaging, and Python tests.

---

## 28. Acceptance criteria

- [ ] Implementation is in `fernme/web/app`, not generated static output.
- [ ] `variables.css` is imported before `theme.css`.
- [ ] No CDN font, icon, D3, or runtime asset is introduced.
- [ ] Graph remains REST-backed.
- [ ] All six main views remain routable.
- [ ] Direct reload under `/ui/*` works.
- [ ] Canonical entity kinds drive graph icons and filter behavior.
- [ ] Graph is the dominant visual surface.
- [ ] Owner is immediately identifiable.
- [ ] At least two communities are visually readable.
- [ ] Animated links are limited to meaningful edges.
- [ ] No React state update occurs per animation frame.
- [ ] Graph resources are cleaned up on component unmount.
- [ ] Reduced-motion mode is respected.
- [ ] Right rail collapses below 1180 px.
- [ ] Left rail becomes a drawer below 900 px.
- [ ] All controls expose visible keyboard focus.
- [ ] Insights are computed, not fabricated.
- [ ] Generated bundle is produced by Vite.
- [ ] Existing frontend, packaging, graph, and full Python tests pass.

---

## 29. Anti-patterns

Do not:

- recreate `graph.html`;
- place the SPA in a single TSX file;
- edit `fernme/web/static/app` by hand;
- import remote CSS, fonts, icons, or D3;
- call React state setters from the animation loop;
- mutate cached API entities with simulation coordinates;
- animate every edge;
- show all labels at every zoom;
- use emoji as graph icons;
- duplicate canonical kind logic in components;
- create fake graph insights;
- use route-specific copies of the token palette;
- render desktop side rails squeezed into mobile width;
- add generic neural-network or AI decorations.

The graph itself is the visual identity.
