import { useEffect, useRef } from "react";
import ForceGraph3D from "3d-force-graph";
import { GraphEdge, GraphNode, nodeId } from "./api";

type FocusState = {
  nodes: Set<string>;
  edges: Set<string>;
} | null;

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  focus: FocusState;
  selectedId: string | null;
  colorFor: (node: GraphNode) => string;
  labelFor: (node: GraphNode) => string;
  relationLabel: (edge: GraphEdge) => string;
  onSelect: (node: GraphNode) => void;
};

function edgeKey(edge: GraphEdge): string {
  return `${nodeId(edge.source)}->${nodeId(edge.target)}`;
}

export default function SpatialGraphView({
  nodes,
  edges,
  focus,
  selectedId,
  colorFor,
  labelFor,
  relationLabel,
  onSelect
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const graphRef = useRef<any>(null);

  useEffect(() => {
    if (!hostRef.current) return;
    if (!graphRef.current) {
      graphRef.current = ForceGraph3D()(hostRef.current)
        .backgroundColor("rgba(0,0,0,0)")
        .nodeId("id")
        .nodeResolution(16)
        .enableNodeDrag(true)
        .showNavInfo(false)
        .onNodeClick((node: GraphNode) => onSelect(node));
    }

    const graph = graphRef.current;
    graph
      .width(hostRef.current.clientWidth)
      .height(hostRef.current.clientHeight)
      .nodeLabel((node: GraphNode) => labelFor(node))
      .nodeColor((node: GraphNode) => {
        const visible = !focus || focus.nodes.has(node.id);
        return visible ? colorFor(node) : "rgba(79, 92, 109, 0.22)";
      })
      .nodeOpacity((node: GraphNode) => (!focus || focus.nodes.has(node.id) ? 0.98 : 0.16))
      .nodeVal((node: GraphNode) => {
        const base = Math.max(3, Math.min(18, Number(node.size || node.weight || 6)));
        return selectedId === node.id ? base * 1.9 : base;
      })
      .linkLabel((edge: GraphEdge) => relationLabel(edge))
      .linkOpacity((edge: GraphEdge) => (!focus || focus.edges.has(edgeKey(edge)) ? 0.42 : 0.06))
      .linkWidth((edge: GraphEdge) => (!focus || focus.edges.has(edgeKey(edge)) ? 1.2 : 0.3))
      .linkColor((edge: GraphEdge) => {
        if (focus && !focus.edges.has(edgeKey(edge))) return "rgba(100,115,132,.12)";
        if (edge.hierarchy_child) return "rgba(157,172,189,.42)";
        if (edge.owner_edge) return "rgba(45,229,182,.55)";
        if (edge.entity_relation) return "rgba(255,155,85,.64)";
        return "rgba(160,186,214,.34)";
      })
      .linkDirectionalParticles((edge: GraphEdge) => selectedId && focus?.edges.has(edgeKey(edge)) ? 3 : 0)
      .linkDirectionalParticleWidth((edge: GraphEdge) => edge.hierarchy_child ? 1.6 : 2.1)
      .linkDirectionalParticleSpeed((edge: GraphEdge) => edge.hierarchy_child ? 0.004 : 0.006)
      .linkDirectionalParticleColor((edge: GraphEdge) => {
        if (edge.hierarchy_child) return "rgba(189,204,220,.78)";
        if (edge.owner_edge) return "rgba(45,229,182,.96)";
        if (edge.entity_relation) return "rgba(255,155,85,.96)";
        return "rgba(176,204,232,.86)";
      })
      .graphData({
        nodes: nodes.map((node, index) => ({
          ...node,
          z: typeof node.z === "number" ? node.z : ((index % 9) - 4) * 18
        })),
        links: edges.map((edge) => ({ ...edge }))
      });

    const resize = new ResizeObserver(() => {
      if (!hostRef.current) return;
      graph.width(hostRef.current.clientWidth);
      graph.height(hostRef.current.clientHeight);
    });
    resize.observe(hostRef.current);

    return () => {
      resize.disconnect();
    };
  }, [colorFor, edges, focus, labelFor, nodes, onSelect, relationLabel, selectedId]);

  useEffect(() => {
    return () => {
      graphRef.current?._destructor?.();
      graphRef.current = null;
    };
  }, []);

  return (
    <div className="spatial-view">
      <div className="spatial-canvas" ref={hostRef} />
      <div className="spatial-badge">Experimental spatial view</div>
    </div>
  );
}
