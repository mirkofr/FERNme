import { lazy, Suspense, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph from "force-graph";
import {
  BarChart3,
  Box,
  BrainCircuit,
  BriefcaseBusiness,
  Building2,
  ChevronDown,
  Crosshair,
  FileText,
  Focus,
  Link2,
  MapPin,
  Maximize2,
  Network,
  Repeat2,
  Search,
  ShieldCheck,
  Sparkles,
  Star,
  UserRound,
  UserRoundCheck,
  WandSparkles,
  Zap
} from "lucide-react";
import { GraphEdge, GraphNode, nodeId, postJson } from "./api";
import { useFern } from "./store";

const FILTER_KEY = "fernme.graph.filters.v1";
const CANONICAL_KINDS = new Set(["person", "org", "project", "place", "thing", "other"]);
const SpatialGraphView = lazy(() => import("./SpatialGraphView"));

type PersistedFilters = {
  catCollapsed?: boolean;
  kindCollapsed?: boolean;
};

function loadFilterState(): PersistedFilters {
  try {
    return JSON.parse(localStorage.getItem(FILTER_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveFilterState(next: PersistedFilters) {
  localStorage.setItem(FILTER_KEY, JSON.stringify({ ...loadFilterState(), ...next }));
}

function categoryOf(node: GraphNode): string {
  return String(node.category || node.cat || node.kind || "Other");
}

function entityKindOf(node: GraphNode): string {
  const fromEntity = typeof node.entity_kind === "string" ? node.entity_kind : "";
  if (fromEntity) {
    return fromEntity;
  }
  const kind = typeof node.kind === "string" ? node.kind : "";
  return CANONICAL_KINDS.has(kind) ? kind : "";
}

function colorFor(node: GraphNode): string {
  if (node.negative) return "#ef6a6a";
  if (node.kind === "user") return "#2de5b6";
  if (entityKindOf(node) === "person") return "#5f7dff";
  if (entityKindOf(node) === "org") return "#24cdb2";
  if (entityKindOf(node) === "project") return "#ff9b55";
  if (entityKindOf(node) === "place") return "#39c7e8";
  if (entityKindOf(node)) return "#b7c0ce";
  return "#87a0b8";
}

function labelFor(node: GraphNode): string {
  return stripNamespace(String(node.entity_display_name || node.label || node.id));
}

function stripNamespace(value: string): string {
  const negativePrefix = value.startsWith("!") ? "!" : "";
  const body = negativePrefix ? value.slice(1) : value;
  const colon = body.indexOf(":");
  if (colon <= 0) {
    return value;
  }
  return `${negativePrefix}${body.slice(colon + 1)}`;
}

function edgeEndpoint(edge: GraphEdge, side: "source" | "target"): string {
  return nodeId(edge[side]);
}

function nodeRadius(node: GraphNode): number {
  return Math.max(5, Math.min(20, Number(node.size || node.weight || 6)));
}

function isOwnerNode(node: GraphNode): boolean {
  return node.kind === "user" || node.kind === "owner" || node.id.startsWith("user:");
}

function edgeIsKnown(edge: GraphEdge): boolean {
  return edge.known === true;
}

function nodeIsExplicitlyUnknown(node: GraphNode): boolean {
  return node.known === false || node.source === "guessed" || node.source === "inferred";
}

function rowKindClass(name: string): string {
  const normalized = name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
  if (normalized.includes("media")) return "filter-row--facts";
  if (normalized.includes("knowledge")) return "filter-row--knowledge";
  if (normalized.includes("milestone")) return "filter-row--milestones";
  if (normalized.includes("habit")) return "filter-row--habits";
  if (normalized.includes("value")) return "filter-row--values";
  if (normalized.includes("user") || normalized.includes("owner")) return "filter-row--user";
  if (normalized.includes("org")) return "filter-row--org";
  if (normalized.includes("project")) return "filter-row--project";
  if (normalized.includes("person") || normalized.includes("people")) return "filter-row--person";
  if (normalized.includes("place")) return "filter-row--place";
  return `filter-row--${normalized}`;
}

function categoryIcon(name: string) {
  const lower = name.toLowerCase();
  if (lower.includes("knowledge")) return <BrainCircuit aria-hidden="true" />;
  if (lower.includes("milestone")) return <Star aria-hidden="true" />;
  if (lower.includes("habit")) return <Repeat2 aria-hidden="true" />;
  if (lower.includes("value")) return <ShieldCheck aria-hidden="true" />;
  if (lower.includes("user") || lower.includes("owner")) return <UserRoundCheck aria-hidden="true" />;
  return <FileText aria-hidden="true" />;
}

function kindIcon(kind: string) {
  if (kind === "person") return <UserRound aria-hidden="true" />;
  if (kind === "org") return <Building2 aria-hidden="true" />;
  if (kind === "project") return <BriefcaseBusiness aria-hidden="true" />;
  if (kind === "place") return <MapPin aria-hidden="true" />;
  if (kind === "thing") return <Box aria-hidden="true" />;
  return <Sparkles aria-hidden="true" />;
}

function canvasIconKind(node: GraphNode): string {
  if (isOwnerNode(node)) return "user";
  const kind = entityKindOf(node);
  if (kind) return kind;
  const category = categoryOf(node).toLowerCase();
  if (category.includes("knowledge")) return "knowledge";
  if (category.includes("milestone")) return "milestone";
  if (category.includes("habit")) return "habit";
  if (category.includes("value")) return "value";
  return "fact";
}

function drawCanvasIcon(node: GraphNode, ctx: CanvasRenderingContext2D, x: number, y: number, radius: number, globalScale: number): void {
  const kind = canvasIconKind(node);
  const unit = Math.max(radius * 0.46, 4 / globalScale);
  const lineWidth = Math.max(1.2 / globalScale, radius * 0.09);

  ctx.save();
  ctx.strokeStyle = "rgba(4, 12, 18, .82)";
  ctx.fillStyle = "rgba(4, 12, 18, .34)";
  ctx.lineWidth = lineWidth;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";

  if (kind === "person" || kind === "user") {
    ctx.beginPath();
    ctx.arc(x, y - unit * 0.34, unit * 0.28, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y + unit * 0.56, unit * 0.54, Math.PI * 1.12, Math.PI * 1.88);
    ctx.stroke();
  } else if (kind === "org") {
    ctx.strokeRect(x - unit * 0.5, y - unit * 0.58, unit, unit * 1.12);
    for (const dx of [-0.22, 0.22]) {
      ctx.beginPath();
      ctx.moveTo(x + unit * dx, y - unit * 0.32);
      ctx.lineTo(x + unit * dx, y + unit * 0.28);
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.moveTo(x - unit * 0.62, y + unit * 0.58);
    ctx.lineTo(x + unit * 0.62, y + unit * 0.58);
    ctx.stroke();
  } else if (kind === "project") {
    ctx.strokeRect(x - unit * 0.62, y - unit * 0.28, unit * 1.24, unit * 0.86);
    ctx.beginPath();
    ctx.moveTo(x - unit * 0.28, y - unit * 0.28);
    ctx.quadraticCurveTo(x, y - unit * 0.72, x + unit * 0.28, y - unit * 0.28);
    ctx.stroke();
  } else if (kind === "place") {
    ctx.beginPath();
    ctx.arc(x, y - unit * 0.12, unit * 0.34, 0, Math.PI * 2);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x, y + unit * 0.62);
    ctx.lineTo(x - unit * 0.36, y + unit * 0.08);
    ctx.lineTo(x + unit * 0.36, y + unit * 0.08);
    ctx.closePath();
    ctx.stroke();
  } else if (kind === "thing") {
    ctx.strokeRect(x - unit * 0.44, y - unit * 0.44, unit * 0.88, unit * 0.88);
    ctx.beginPath();
    ctx.moveTo(x - unit * 0.44, y - unit * 0.1);
    ctx.lineTo(x + unit * 0.44, y - unit * 0.1);
    ctx.stroke();
  } else if (kind === "knowledge") {
    ctx.beginPath();
    ctx.moveTo(x - unit * 0.56, y - unit * 0.1);
    ctx.quadraticCurveTo(x - unit * 0.24, y - unit * 0.54, x, y - unit * 0.14);
    ctx.quadraticCurveTo(x + unit * 0.24, y - unit * 0.54, x + unit * 0.56, y - unit * 0.1);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x, y - unit * 0.14);
    ctx.lineTo(x, y + unit * 0.52);
    ctx.stroke();
  } else if (kind === "value") {
    ctx.beginPath();
    ctx.moveTo(x, y - unit * 0.58);
    ctx.lineTo(x + unit * 0.52, y - unit * 0.28);
    ctx.lineTo(x + unit * 0.42, y + unit * 0.42);
    ctx.lineTo(x, y + unit * 0.64);
    ctx.lineTo(x - unit * 0.42, y + unit * 0.42);
    ctx.lineTo(x - unit * 0.52, y - unit * 0.28);
    ctx.closePath();
    ctx.stroke();
  } else {
    ctx.beginPath();
    ctx.moveTo(x, y - unit * 0.62);
    ctx.lineTo(x + unit * 0.18, y - unit * 0.16);
    ctx.lineTo(x + unit * 0.62, y);
    ctx.lineTo(x + unit * 0.18, y + unit * 0.16);
    ctx.lineTo(x, y + unit * 0.62);
    ctx.lineTo(x - unit * 0.18, y + unit * 0.16);
    ctx.lineTo(x - unit * 0.62, y);
    ctx.lineTo(x - unit * 0.18, y - unit * 0.16);
    ctx.closePath();
    ctx.stroke();
  }

  ctx.restore();
}

function titleCase(value: string): string {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function edgeKey(edge: GraphEdge): string {
  return `${edgeEndpoint(edge, "source")}->${edgeEndpoint(edge, "target")}`;
}

function normalizedEdgeKey(source: string, target: string): string {
  return source <= target ? `${source}->${target}` : `${target}->${source}`;
}

function relationLabel(edge: GraphEdge): string {
  const label = String(edge.label || edge.relation || (edge.hierarchy_child ? "contains" : "related to"));
  const factCount = typeof edge.fact_count === "number"
    ? edge.fact_count
    : Array.isArray(edge.facts) ? edge.facts.length : 0;
  return factCount > 0 ? `${label} (${factCount} facts)` : label;
}

function relationTooltipKey(edge: GraphEdge): string {
  return `${normalizedEdgeKey(edgeEndpoint(edge, "source"), edgeEndpoint(edge, "target"))}:${relationLabel(edge)}:${edge.hierarchy_child ? "child" : ""}:${edge.owner_edge ? "owner" : ""}`;
}

function drawRelationTooltip(edge: GraphEdge, ctx: CanvasRenderingContext2D, globalScale: number): void {
  const source = edge.source as GraphNode;
  const target = edge.target as GraphNode;
  if (typeof source.x !== "number" || typeof source.y !== "number" || typeof target.x !== "number" || typeof target.y !== "number") {
    return;
  }
  const label = relationLabel(edge);
  const x = (source.x + target.x) / 2;
  const y = (source.y + target.y) / 2;
  const fontSize = Math.max(12 / globalScale, 5);
  const paddingX = 6 / globalScale;
  const paddingY = 4 / globalScale;
  ctx.save();
  ctx.font = `700 ${fontSize}px Inter, system-ui, sans-serif`;
  const width = ctx.measureText(label).width + paddingX * 2;
  const height = fontSize + paddingY * 2;
  ctx.fillStyle = "rgba(0, 0, 0, .88)";
  ctx.fillRect(x - width / 2, y - height / 2, width, height);
  ctx.fillStyle = "#f7fafc";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, x, y);
  ctx.restore();
}

type FocusState = {
  nodes: Set<string>;
  edges: Set<string>;
};

export default function GraphView() {
  const fern = useFern();
  const hostRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<any>(null);
  const graphHostRef = useRef<HTMLDivElement | null>(null);
  const hoveredLinkRef = useRef<GraphEdge | null>(null);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [search, setSearch] = useState("");
  const [kindQuery, setKindQuery] = useState("");
  const saved = useMemo(loadFilterState, []);
  const [catCollapsed, setCatCollapsed] = useState(Boolean(saved.catCollapsed));
  const [kindCollapsed, setKindCollapsed] = useState(saved.kindCollapsed ?? true);
  const [viewMode, setViewMode] = useState<"2d" | "spatial">("2d");

  const categories = useMemo(() => {
    const nodes = fern.graph?.nodes || [];
    return Array.from(new Set(nodes.map(categoryOf))).sort();
  }, [fern.graph]);

  const entityKinds = useMemo(() => {
    const fromGraph = fern.graph?.entity_kinds || [];
    const fromNodes = (fern.graph?.nodes || []).map(entityKindOf).filter(Boolean);
    return Array.from(new Set([...fromGraph, ...fromNodes])).filter((kind) => CANONICAL_KINDS.has(kind)).sort();
  }, [fern.graph]);

  const [selectedCats, setSelectedCats] = useState<Set<string>>(new Set());
  const [selectedKinds, setSelectedKinds] = useState<Set<string>>(new Set());

  useEffect(() => {
    setSelectedCats((current) => current.size ? new Set([...current].filter((cat) => categories.includes(cat))) : new Set(categories));
  }, [categories]);

  useEffect(() => {
    setSelectedKinds((current) => current.size ? new Set([...current].filter((kind) => entityKinds.includes(kind))) : new Set(entityKinds));
    if (saved.kindCollapsed === undefined) {
      setKindCollapsed(entityKinds.length > 12);
    }
  }, [entityKinds, saved.kindCollapsed]);

  const visibleKinds = useMemo(
    () => entityKinds.filter((kind) => kind.toLowerCase().includes(kindQuery.trim().toLowerCase())),
    [entityKinds, kindQuery]
  );

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of fern.graph?.nodes || []) {
      const category = categoryOf(node);
      counts.set(category, (counts.get(category) || 0) + 1);
    }
    return counts;
  }, [fern.graph]);

  const kindCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const node of fern.graph?.nodes || []) {
      const kind = entityKindOf(node);
      if (kind) {
        counts.set(kind, (counts.get(kind) || 0) + 1);
      }
    }
    return counts;
  }, [fern.graph]);

  const filtered = useMemo(() => {
    const sourceNodes = fern.graph?.nodes || [];
    const sourceEdges = fern.graph?.edges || [];
    const assignments = fern.graph?.hierarchy?.assignments || {};
    const ownerEdges = fern.graph?.hierarchy?.owner_edges || [];
    const knownNodeIds = new Set<string>();
    if (fern.knownOnly) {
      for (const node of sourceNodes) {
        if (isOwnerNode(node) && !nodeIsExplicitlyUnknown(node)) {
          knownNodeIds.add(node.id);
        }
      }
      for (const edge of [...sourceEdges, ...ownerEdges]) {
        if (!edgeIsKnown(edge)) continue;
        knownNodeIds.add(edgeEndpoint(edge, "source"));
        knownNodeIds.add(edgeEndpoint(edge, "target"));
      }
    }
    const nodes = sourceNodes.filter((node) => {
      if (selectedCats.size && !selectedCats.has(categoryOf(node))) return false;
      const kind = entityKindOf(node);
      if (kind && selectedKinds.size && !selectedKinds.has(kind)) return false;
      if (fern.knownOnly && nodeIsExplicitlyUnknown(node)) return false;
      if (fern.knownOnly && !knownNodeIds.has(node.id)) return false;
      return true;
    });
    const ids = new Set(nodes.map((node) => node.id));
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const edges: GraphEdge[] = [];
    const seen = new Set<string>();
    const addEdge = (edge: GraphEdge) => {
      const source = edgeEndpoint(edge, "source");
      const target = edgeEndpoint(edge, "target");
      if (!ids.has(source) || !ids.has(target)) return;
      const key = `${normalizedEdgeKey(source, target)}:${edge.relation || edge.label || ""}:${edge.hierarchy_child ? "child" : ""}:${edge.owner_edge ? "owner" : ""}`;
      if (seen.has(key)) return;
      seen.add(key);
      edges.push(edge);
    };

    for (const edge of sourceEdges) {
      if (fern.knownOnly && edge.known === false) continue;
      const source = edgeEndpoint(edge, "source");
      const target = edgeEndpoint(edge, "target");
      if (!ids.has(source) || !ids.has(target)) continue;
      const sourceOwner = isOwnerNode(nodeById.get(source) || ({ id: source } as GraphNode));
      const targetOwner = isOwnerNode(nodeById.get(target) || ({ id: target } as GraphNode));
      const ownerLinkedAttr = sourceOwner ? target : targetOwner ? source : "";
      const parent = ownerLinkedAttr ? assignments[ownerLinkedAttr] : "";

      if (parent && parent !== ownerLinkedAttr) {
        continue;
      }
      if (parent && ownerEdges.length) {
        continue;
      }
      addEdge(edge);
    }

    for (const edge of ownerEdges) {
      if (fern.knownOnly && !edgeIsKnown(edge)) continue;
      addEdge({
        ...edge,
        owner_edge: true,
        hierarchy_edge: true,
        relation: edge.relation || "related to",
        label: edge.label || "related to"
      });
    }

    for (const [child, parent] of Object.entries(assignments)) {
      if (child === parent || parent === "__unclustered__") continue;
      addEdge({
        source: parent,
        target: child,
        hierarchy_child: true,
        hierarchy_edge: true,
        relation: "contains",
        label: "contains",
        weight: 0.8
      });
    }

    return { nodes, edges };
  }, [fern.graph, fern.knownOnly, selectedCats, selectedKinds]);

  const overviewFocus = useMemo<FocusState | null>(() => {
    if (!filtered.nodes.length) {
      return null;
    }
    const focusNodes = new Set<string>();
    const focusEdges = new Set<string>();
    const assignments = fern.graph?.hierarchy?.assignments || {};
    const anchorIds = new Set(
      Object.entries(assignments)
        .filter(([child, parent]) => child === parent && parent !== "__unclustered__")
        .map(([child]) => child)
    );

    for (const node of filtered.nodes) {
      if (isOwnerNode(node) || anchorIds.has(node.id)) {
        focusNodes.add(node.id);
      }
    }

    for (const edge of filtered.edges) {
      const source = edgeEndpoint(edge, "source");
      const target = edgeEndpoint(edge, "target");
      if (edge.owner_edge && focusNodes.has(source) && focusNodes.has(target)) {
        focusEdges.add(edgeKey(edge));
      } else if (edge.entity_relation && focusNodes.has(source) && focusNodes.has(target)) {
        focusEdges.add(edgeKey(edge));
      }
    }

    if (!focusNodes.size) {
      return null;
    }
    return { nodes: focusNodes, edges: focusEdges };
  }, [fern.graph, filtered]);

  const focus = useMemo(() => {
    if (!selected) {
      return overviewFocus;
    }
    const focusNodes = new Set<string>([selected.id]);
    const focusEdges = new Set<string>();
    const assignments = fern.graph?.hierarchy?.assignments || {};
    const ownerEdges = fern.graph?.hierarchy?.owner_edges || [];
    const selectedParent = assignments[selected.id];

    if (isOwnerNode(selected)) {
      for (const edge of filtered.edges) {
        const source = edgeEndpoint(edge, "source");
        const target = edgeEndpoint(edge, "target");
        if (source === selected.id || target === selected.id) {
          focusNodes.add(source);
          focusNodes.add(target);
          focusEdges.add(edgeKey(edge));
        }
      }
      for (const edge of ownerEdges) {
        if (edgeEndpoint(edge, "source") === selected.id || edgeEndpoint(edge, "target") === selected.id) {
          focusNodes.add(edgeEndpoint(edge, "source"));
          focusNodes.add(edgeEndpoint(edge, "target"));
        }
      }
      return { nodes: focusNodes, edges: focusEdges };
    }

    if (selectedParent) {
      focusNodes.add(selectedParent);
      for (const [child, parent] of Object.entries(assignments)) {
        if (parent === selectedParent) {
          focusNodes.add(child);
        }
      }
    }

    for (const edge of filtered.edges) {
      const source = edgeEndpoint(edge, "source");
      const target = edgeEndpoint(edge, "target");
      const sourceInFocus = focusNodes.has(source);
      const targetInFocus = focusNodes.has(target);
      if (sourceInFocus && targetInFocus) {
        focusEdges.add(edgeKey(edge));
      } else if (!selectedParent && (source === selected.id || target === selected.id)) {
        focusNodes.add(source);
        focusNodes.add(target);
        focusEdges.add(edgeKey(edge));
      }
    }

    return { nodes: focusNodes, edges: focusEdges };
  }, [fern.graph, filtered.edges, overviewFocus, selected]);

  useEffect(() => {
    if (viewMode !== "2d") {
      graphRef.current?._destructor?.();
      graphRef.current = null;
      graphHostRef.current = null;
      hoveredLinkRef.current = null;
      return;
    }
    if (!hostRef.current) return;
    if (!graphRef.current || graphHostRef.current !== hostRef.current) {
      graphRef.current?._destructor?.();
      graphRef.current = ForceGraph()(hostRef.current)
        .nodeId("id")
        .nodeRelSize(4);
      graphHostRef.current = hostRef.current;
    }

    const graph = graphRef.current;
    graph
      .nodeLabel((node: GraphNode) => labelFor(node))
      .linkLabel((edge: GraphEdge) => relationLabel(edge))
      .linkHoverPrecision(8)
      .nodePointerAreaPaint((node: GraphNode, color: string, ctx: CanvasRenderingContext2D) => {
        const radius = nodeRadius(node) + 10;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(Number(node.x), Number(node.y), radius, 0, 2 * Math.PI, false);
        ctx.fill();
      })
      .linkWidth((edge: GraphEdge) => {
        const focused = !focus || focus.edges.has(edgeKey(edge));
        const base = edge.hierarchy_child ? 0.9 : edge.owner_edge ? 1.4 : edge.entity_relation ? 1.8 : edge.assoc ? 0.7 : 1.2;
        return focused ? base : 0.45;
      })
      .linkColor((edge: GraphEdge) => {
        const focused = !focus || focus.edges.has(edgeKey(edge));
        if (!focused) return "rgba(95,111,129,.13)";
        if (edge.negative) return "rgba(239,106,106,.72)";
        if (edge.hierarchy_child) return "rgba(157,172,189,.38)";
        if (edge.owner_edge) return "rgba(164,184,204,.55)";
        if (edge.entity_relation) return "rgba(240,163,64,.78)";
        return "rgba(164,184,204,.48)";
      })
      .linkDirectionalParticles((edge: GraphEdge) => selected && focus?.edges.has(edgeKey(edge)) ? 3 : 0)
      .linkDirectionalParticleWidth((edge: GraphEdge) => {
        const hovered = hoveredLinkRef.current;
        return hovered && relationTooltipKey(edge) === relationTooltipKey(hovered) ? 3 : 2;
      })
      .linkDirectionalParticleSpeed((edge: GraphEdge) => edge.hierarchy_child ? 0.005 : 0.007)
      .linkDirectionalParticleColor((edge: GraphEdge) => {
        if (edge.negative) return "rgba(239,106,106,.9)";
        if (edge.hierarchy_child) return "rgba(189,204,220,.72)";
        if (edge.owner_edge) return "rgba(45,229,182,.92)";
        if (edge.entity_relation) return "rgba(255,155,85,.92)";
        return "rgba(176,204,232,.82)";
      })
      .onNodeClick((node: GraphNode) => setSelected(node))
      .onBackgroundClick(() => setSelected(null))
      .onLinkHover((edge: GraphEdge | null) => {
        hoveredLinkRef.current = edge;
        graphRef.current?.refresh?.();
      })
      .linkCanvasObjectMode((edge: GraphEdge) => {
        const hovered = hoveredLinkRef.current;
        return hovered && relationTooltipKey(edge) === relationTooltipKey(hovered) ? "after" : undefined;
      })
      .linkCanvasObject((edge: GraphEdge, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const hovered = hoveredLinkRef.current;
        if (hovered && relationTooltipKey(edge) === relationTooltipKey(hovered)) {
          drawRelationTooltip(edge, ctx, globalScale);
        }
      })
      .nodeCanvasObject((node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
        const label = labelFor(node);
        const radius = nodeRadius(node);
        const focused = !focus || focus.nodes.has(node.id);
        ctx.beginPath();
        ctx.arc(Number(node.x), Number(node.y), radius, 0, 2 * Math.PI, false);
        ctx.fillStyle = colorFor(node);
        ctx.globalAlpha = focused ? 1 : 0.18;
        ctx.fill();
        if (selected?.id === node.id) {
          ctx.lineWidth = 2.2 / globalScale;
          ctx.strokeStyle = "#f6f0df";
          ctx.stroke();
        }
        drawCanvasIcon(node, ctx, Number(node.x), Number(node.y), radius, globalScale);
        if (focused && (globalScale > 0.65 || selected?.id === node.id)) {
          const fontSize = Math.max(10 / globalScale, 5);
          ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
          ctx.fillStyle = "rgba(238,243,248,.92)";
          ctx.fillText(label.slice(0, 34), Number(node.x) + radius + 3, Number(node.y) + 3);
        }
        ctx.globalAlpha = 1;
      });

    graph.width(hostRef.current.clientWidth);
    graph.height(hostRef.current.clientHeight);
    graph.graphData({
      nodes: filtered.nodes.map((node) => ({ ...node })),
      links: filtered.edges.map((edge) => ({ ...edge }))
    });

    const resize = new ResizeObserver(() => {
      if (!hostRef.current) return;
      graph.width(hostRef.current.clientWidth);
      graph.height(hostRef.current.clientHeight);
    });
    resize.observe(hostRef.current);
    return () => resize.disconnect();
  }, [filtered, focus, selected, viewMode]);

  useEffect(() => {
    return () => {
      graphRef.current?._destructor?.();
      graphRef.current = null;
      graphHostRef.current = null;
    };
  }, []);

  const focusSearch = () => {
    const term = search.trim().toLowerCase();
    if (!term || !graphRef.current) return;
    const node = filtered.nodes.find((item) => labelFor(item).toLowerCase().includes(term) || item.id.toLowerCase().includes(term));
    if (!node) return;
    setSelected(node);
    graphRef.current.centerAt((node as any).x || 0, (node as any).y || 0, 600);
    graphRef.current.zoom(3, 600);
  };

  useEffect(() => {
    const rawTerm = fern.contextText.split(",")[0]?.trim().toLowerCase() || "";
    if (!rawTerm) return;
    const bareTerm = rawTerm.includes(":") ? rawTerm.slice(rawTerm.lastIndexOf(":") + 1) : rawTerm;
    const match = filtered.nodes.find((node) => {
      const id = node.id.toLowerCase();
      const label = labelFor(node).toLowerCase();
      return id === rawTerm || id.endsWith(`:${bareTerm}`) || label === bareTerm || label.includes(bareTerm);
    });
    if (!match || selected?.id === match.id) return;
    setSelected(match);
    graphRef.current?.centerAt?.((match as any).x || 0, (match as any).y || 0, 650);
    graphRef.current?.zoom?.(2.6, 650);
  }, [fern.contextText, filtered.nodes, selected?.id]);

  return (
    <section className="workspace graph-route">
      <aside className="filter-rail" aria-label="Graph filters">
        <FilterSection
          title="Categories"
          icon={<Box aria-hidden="true" />}
          collapsed={catCollapsed}
          onToggle={() => {
            setCatCollapsed(!catCollapsed);
            saveFilterState({ catCollapsed: !catCollapsed });
          }}
          onSelectAll={() => setSelectedCats(new Set(categories))}
          onClear={() => setSelectedCats(new Set())}
        >
          <ul className="filter-list">
            {categories.map((cat) => (
              <li key={cat}>
                <button
                  type="button"
                  className={`filter-row ${rowKindClass(cat)}`}
                  aria-pressed={selectedCats.has(cat)}
                  title={cat}
                  onClick={() => toggleSet(selectedCats, setSelectedCats, cat)}
                >
                  <span className="filter-row__icon">{categoryIcon(cat)}</span>
                  <span className="filter-row__label">{titleCase(cat)}</span>
                  <span className="filter-row__count">{categoryCounts.get(cat) || 0}</span>
                </button>
              </li>
            ))}
          </ul>
        </FilterSection>
        <FilterSection
          title="Entity kinds"
          icon={<Network aria-hidden="true" />}
          collapsed={kindCollapsed}
          onToggle={() => {
            setKindCollapsed(!kindCollapsed);
            saveFilterState({ kindCollapsed: !kindCollapsed });
          }}
          onSelectAll={() => setSelectedKinds(new Set(entityKinds))}
          onClear={() => setSelectedKinds(new Set())}
        >
          <label className="search-control filter-search">
            <Search className="search-control__icon" aria-hidden="true" />
            <input
              aria-label="Filter entity kinds"
              placeholder="Filter kinds"
              value={kindQuery}
              onChange={(event) => setKindQuery(event.target.value)}
            />
          </label>
          <ul className="filter-list">
            {visibleKinds.map((kind) => (
              <li key={kind}>
                <button
                  type="button"
                  className={`filter-row ${rowKindClass(kind)}`}
                  aria-pressed={selectedKinds.has(kind)}
                  title={kind}
                  onClick={() => toggleSet(selectedKinds, setSelectedKinds, kind)}
                >
                  <span className="filter-row__icon">{kindIcon(kind)}</span>
                  <span className="filter-row__label">{titleCase(kind)}</span>
                  <span className="filter-row__count">{kindCounts.get(kind) || 0}</span>
                </button>
              </li>
            ))}
          </ul>
        </FilterSection>
        <section className="panel filter-card saved-filters">
          <div className="panel__header">
            <h2 className="panel__title"><ShieldCheck className="icon" aria-hidden="true" /> Saved filters</h2>
            <ChevronDown className="icon" aria-hidden="true" />
          </div>
        </section>
      </aside>

      <section className="graph-workspace" aria-label="Memory graph">
        <div className="graph-toolbar">
          <label className="search-control">
            <Search className="search-control__icon" aria-hidden="true" />
            <input
              aria-label="Search memory graph"
              list="graph-nodes"
              placeholder="Search memory graph..."
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") focusSearch();
              }}
            />
          </label>
          <datalist id="graph-nodes">
            {filtered.nodes.slice(0, 250).map((node) => <option key={node.id} value={labelFor(node)} />)}
          </datalist>
          <button type="button" className="button" onClick={focusSearch}>
            <Focus className="icon" aria-hidden="true" /> Focus
          </button>
          <button type="button" className="button" onClick={() => graphRef.current?.zoomToFit?.(500, 60)}>
            <Maximize2 className="icon" aria-hidden="true" /> Fit
          </button>
          <button
            type="button"
            className="switch-control"
            role="switch"
            aria-checked={fern.knownOnly}
            onClick={() => fern.setKnownOnly(!fern.knownOnly)}
          >
            <span className="switch" aria-hidden="true" />
            Known only
          </button>
          <div className="segmented-control" aria-label="Graph view mode">
            <button type="button" className={viewMode === "2d" ? "is-active" : ""} onClick={() => setViewMode("2d")}>2D</button>
            <button type="button" className={viewMode === "spatial" ? "is-active" : ""} onClick={() => setViewMode("spatial")}>Spatial</button>
          </div>
        </div>
        <div className="graph-stage">
          {viewMode === "spatial" ? (
            <Suspense fallback={<div className="spatial-loading">Loading spatial view...</div>}>
              <SpatialGraphView
                nodes={filtered.nodes}
                edges={filtered.edges}
                focus={focus}
                selectedId={selected?.id || null}
                colorFor={colorFor}
                labelFor={labelFor}
                relationLabel={relationLabel}
                onSelect={setSelected}
              />
            </Suspense>
          ) : (
            <div ref={hostRef} className="graph-canvas" />
          )}
          <div className="graph-floating graph-status">
            <span className="live-dot is-animated" />
            <span className="graph-status__primary">Live</span>
            <span>Synced locally</span>
          </div>
          <div className="graph-floating graph-realtime">
            <Zap className="icon" aria-hidden="true" /> Realtime updates active
          </div>
        </div>
      </section>

      <GraphInsights
        nodes={filtered.nodes}
        edges={filtered.edges}
        totalNodes={fern.graph?.nodes?.length || 0}
        totalEdges={fern.graph?.edges?.length || 0}
        suggestions={fern.suggestions.length}
      />
      <Inspector node={selected} onClose={() => setSelected(null)} onEdit={fern.editAttr} />
    </section>
  );
}

function FilterSection({
  title,
  icon,
  collapsed,
  onToggle,
  onSelectAll,
  onClear,
  children
}: {
  title: string;
  icon: React.ReactNode;
  collapsed: boolean;
  onToggle: () => void;
  onSelectAll: () => void;
  onClear: () => void;
  children: React.ReactNode;
}) {
  return (
    <section className="panel filter-card">
      <div className="panel__header">
        <h2 className="panel__title"><span className="icon">{icon}</span>{title}</h2>
        <button type="button" className="button button--ghost button--icon" onClick={onToggle} aria-expanded={!collapsed}>
          <ChevronDown className={collapsed ? "icon" : "icon rotate-open"} aria-hidden="true" />
        </button>
      </div>
      <div className="panel__actions">
        <button type="button" className="panel__action" onClick={onSelectAll}>Select all</button>
        <button type="button" className="panel__action" onClick={onClear}>Clear</button>
      </div>
      {collapsed ? null : children}
    </section>
  );
}

function toggleSet(values: Set<string>, update: (next: Set<string>) => void, value: string) {
  const next = new Set(values);
  if (next.has(value)) {
    next.delete(value);
  } else {
    next.add(value);
  }
  update(next);
}

function Stats({ nodes, links }: { nodes: number; links: number }) {
  return (
    <aside className="graph-stats">
      <strong>{nodes}</strong> visible nodes
      <strong>{links}</strong> visible links
    </aside>
  );
}

function GraphInsights({
  nodes,
  edges,
  totalNodes,
  totalEdges,
  suggestions
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  totalNodes: number;
  totalEdges: number;
  suggestions: number;
}) {
  const topNode = useMemo(() => {
    const degree = new Map<string, number>();
    for (const edge of edges) {
      const source = edgeEndpoint(edge, "source");
      const target = edgeEndpoint(edge, "target");
      degree.set(source, (degree.get(source) || 0) + 1);
      degree.set(target, (degree.get(target) || 0) + 1);
    }
    const nodeById = new Map(nodes.map((node) => [node.id, node]));
    const best = Array.from(degree.entries()).sort((a, b) => b[1] - a[1])[0];
    return best ? { node: nodeById.get(best[0]), degree: best[1] } : null;
  }, [edges, nodes]);

  const projectNode = useMemo(() => {
    const projects = nodes.filter((node) => entityKindOf(node) === "project");
    if (!projects.length) return null;
    const degree = new Map<string, number>();
    for (const edge of edges) {
      degree.set(edgeEndpoint(edge, "source"), (degree.get(edgeEndpoint(edge, "source")) || 0) + 1);
      degree.set(edgeEndpoint(edge, "target"), (degree.get(edgeEndpoint(edge, "target")) || 0) + 1);
    }
    return projects.sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0))[0];
  }, [edges, nodes]);

  const legend = [
    ["Person", "var(--fern-graph-person)"],
    ["Organization", "var(--fern-graph-organization)"],
    ["Project", "var(--fern-graph-project)"],
    ["Concept", "var(--fern-graph-concept)"],
    ["Place", "var(--fern-graph-place)"],
    ["Event / Milestone", "var(--fern-graph-event)"],
  ];

  return (
    <aside className="insight-rail" aria-label="Graph insights">
      <section className="panel summary-card">
        <div className="summary-metric">
          <Network className="summary-metric__icon" aria-hidden="true" />
          <div>
            <div className="summary-metric__label">Visible nodes</div>
            <div className="summary-metric__value">{nodes.length}</div>
            <div className="summary-metric__total">of {totalNodes || nodes.length}</div>
          </div>
        </div>
        <div className="summary-metric">
          <Link2 className="summary-metric__icon" aria-hidden="true" />
          <div>
            <div className="summary-metric__label">Visible links</div>
            <div className="summary-metric__value">{edges.length}</div>
            <div className="summary-metric__total">of {totalEdges || edges.length}</div>
          </div>
        </div>
      </section>
      <section className="panel insight-card">
        <div className="panel__header">
          <h2 className="panel__title"><BarChart3 className="icon" aria-hidden="true" /> Graph insights</h2>
          <ChevronDown className="icon" aria-hidden="true" />
        </div>
        <ul className="insight-list">
          <li className="insight-item">
            <span className="insight-item__icon"><Sparkles aria-hidden="true" /></span>
            <span>
              <span className="insight-item__title">Top central entity</span>
              <span className="insight-item__body">{topNode?.node ? labelFor(topNode.node) : "No connected entity"}</span>
              {topNode ? <span className="insight-chip">Degree {topNode.degree}</span> : null}
            </span>
          </li>
          <li className="insight-item">
            <span className="insight-item__icon"><BriefcaseBusiness aria-hidden="true" /></span>
            <span>
              <span className="insight-item__title">Most connected project</span>
              <span className="insight-item__body">{projectNode ? labelFor(projectNode) : "No visible project"}</span>
            </span>
          </li>
          <li className="insight-item">
            <span className="insight-item__icon"><WandSparkles aria-hidden="true" /></span>
            <span>
              <span className="insight-item__title">Review queue</span>
              <span className="insight-item__body">{suggestions} pending suggestions</span>
            </span>
          </li>
        </ul>
      </section>
      <section className="panel legend-card">
        <ul className="legend-list">
          {legend.map(([label, color]) => (
            <li className="legend-item" key={label}>
              <span className="legend-dot" style={{ "--legend-color": color } as React.CSSProperties} />
              <span>{label}</span>
            </li>
          ))}
        </ul>
      </section>
    </aside>
  );
}

function Inspector({
  node,
  onClose,
  onEdit
}: {
  node: GraphNode | null;
  onClose: () => void;
  onEdit: (attr: string, weight: number) => Promise<void>;
}) {
  const fern = useFern();
  const [why, setWhy] = useState<unknown>(null);
  const [confidence, setConfidence] = useState<unknown>(null);

  useEffect(() => {
    setWhy(null);
    setConfidence(null);
    if (!node || node.kind === "user") return;
    const attr = String(node.label || node.id);
    Promise.allSettled([
      postJson("/why", { site: fern.site, user: fern.user, attr }),
      postJson("/confidence", { site: fern.site, user: fern.user, attr })
    ]).then(([whyResult, confidenceResult]) => {
      if (whyResult.status === "fulfilled") setWhy(whyResult.value);
      if (confidenceResult.status === "fulfilled") setConfidence(confidenceResult.value);
    });
  }, [fern.site, fern.user, node]);

  if (!node) return null;
  const attr = String(node.label || node.id);
  return (
    <aside className="inspector">
      <div className="inspector-head">
        <h2 title={labelFor(node)}>{labelFor(node)}</h2>
        <button type="button" onClick={onClose}>Close</button>
      </div>
      <dl>
        <dt>Kind</dt>
        <dd>{entityKindOf(node) || node.kind || "attribute"}</dd>
        <dt>Strength</dt>
        <dd>{String(node.weight || node.size || "n/a")}</dd>
        <dt>Aliases</dt>
        <dd>{(node.entity_aliases || node.collapsed_aliases || []).join(", ") || "none"}</dd>
      </dl>
      {node.kind !== "user" ? (
        <label className="weight-edit">
          <span>Set weight</span>
          <input
            type="number"
            min="0"
            max="9"
            defaultValue={Number(node.weight || node.size || 1)}
            onBlur={(event) => onEdit(attr, Number(event.target.value))}
          />
        </label>
      ) : null}
      <h3>Why</h3>
      <pre>{JSON.stringify(why || {}, null, 2)}</pre>
      <h3>Confidence</h3>
      <pre>{JSON.stringify(confidence || {}, null, 2)}</pre>
    </aside>
  );
}
