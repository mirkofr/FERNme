export type GraphNode = {
  id: string;
  label?: string;
  kind?: string;
  category?: string;
  cat?: string;
  size?: number;
  weight?: number;
  negative?: boolean;
  known?: boolean;
  entity_kind?: string;
  entity_display_name?: string;
  entity_aliases?: string[];
  collapsed_aliases?: string[];
  owner_entity?: boolean;
  x?: number;
  y?: number;
  z?: number;
  [key: string]: unknown;
};

export type GraphEdge = {
  source: string | GraphNode;
  target: string | GraphNode;
  label?: string;
  relation?: string;
  weight?: number;
  confidence?: number;
  known?: boolean;
  negative?: boolean;
  assoc?: boolean;
  entity_relation?: boolean;
  [key: string]: unknown;
};

export type GraphData = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  categories?: Record<string, string>;
  cats?: Record<string, string>;
  entity_kinds?: string[];
  stats?: Record<string, unknown>;
  hierarchy?: {
    assignments?: Record<string, string>;
    owner_edges?: GraphEdge[];
    expanded_edges?: GraphEdge[];
    [key: string]: unknown;
  };
  entities?: Record<string, unknown>[];
  entity_aliases?: Record<string, string>;
  entity_relations?: Record<string, unknown>[];
  document_overlay?: {
    enabled: boolean;
    truncated: boolean;
    next_cursor?: string | null;
    document_count: number;
    link_count: number;
    limit: number;
    content_redacted: boolean;
  };
};

export type PromptCard = {
  links?: Array<{ attr: string; weight?: number; confidence?: number; source?: string; known?: boolean }>;
  numeric?: Record<string, unknown>;
  entities?: unknown[];
  [key: string]: unknown;
};

export type Suggestion = {
  id?: string;
  suggestion_id?: string;
  kind?: string;
  score?: number;
  payload?: Record<string, unknown>;
  evidence?: unknown;
  [key: string]: unknown;
};

export type RecallReplay = {
  seeds: string[];
  steps: Array<{
    attr: string;
    activation: number;
    weight: number;
    confidence: number;
    in_card: boolean;
    neighbors?: Array<{ attr: string; weight: number }>;
  }>;
  card_attrs: string[];
  population_prior?: { n_users: number };
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers || {})
    }
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function getJson<T>(path: string): Promise<T> {
  return request<T>(path);
}

export function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: JSON.stringify(body)
  });
}

export function nodeId(value: string | GraphNode): string {
  return typeof value === "string" ? value : value.id;
}
