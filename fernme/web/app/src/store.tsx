import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { getJson, GraphData, postJson, PromptCard, RecallReplay, Suggestion } from "./api";

type RuntimeDefaults = { site: string; user: string };

const CONTEXT_KEY = "fernme.ui.context.v1";

type FernState = {
  site: string;
  user: string;
  contextText: string;
  assocFloor: number;
  knownOnly: boolean;
  graph: GraphData | null;
  card: PromptCard | null;
  suggestions: Suggestion[];
  events: unknown[];
  audit: unknown[];
  replay: RecallReplay | null;
  health: Record<string, unknown> | null;
  loading: boolean;
  error: string | null;
  setSite: (value: string) => void;
  setUser: (value: string) => void;
  setContextText: (value: string) => void;
  setAssocFloor: (value: number) => void;
  setKnownOnly: (value: boolean) => void;
  refreshAll: () => Promise<void>;
  refreshGraph: () => Promise<void>;
  refreshSuggestions: () => Promise<void>;
  acceptSuggestion: (suggestion: Suggestion) => Promise<void>;
  rejectSuggestion: (suggestion: Suggestion) => Promise<void>;
  editAttr: (attr: string, weight: number) => Promise<void>;
  forgetUser: () => Promise<void>;
};

const FernContext = createContext<FernState | null>(null);

function splitContext(text: string): string[] {
  return text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function suggestionId(suggestion: Suggestion): string {
  return String(suggestion.suggestion_id || suggestion.id || "");
}

function readSavedContext(): Partial<RuntimeDefaults> {
  try {
    const saved = JSON.parse(localStorage.getItem(CONTEXT_KEY) || "{}");
    return {
      site: typeof saved.site === "string" ? saved.site : undefined,
      user: typeof saved.user === "string" ? saved.user : undefined
    };
  } catch {
    return {};
  }
}

export function FernProvider({ children }: { children: React.ReactNode }) {
  const savedContext = useMemo(readSavedContext, []);
  const [site, setSiteState] = useState(savedContext.site || "default");
  const [user, setUserState] = useState(savedContext.user || "default");
  const [contextText, setContextText] = useState("");
  const [assocFloor, setAssocFloor] = useState(1);
  const [knownOnly, setKnownOnly] = useState(true);
  const [graph, setGraph] = useState<GraphData | null>(null);
  const [card, setCard] = useState<PromptCard | null>(null);
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [events, setEvents] = useState<unknown[]>([]);
  const [audit, setAudit] = useState<unknown[]>([]);
  const [replay, setReplay] = useState<RecallReplay | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const payload = useMemo(() => ({ site, user }), [site, user]);
  const context = useMemo(() => splitContext(contextText), [contextText]);

  const setSite = useCallback((value: string) => {
    setSiteState(value);
  }, []);

  const setUser = useCallback((value: string) => {
    setUserState(value);
  }, []);

  useEffect(() => {
    getJson<RuntimeDefaults>("/runtime-defaults")
      .then((defaults) => {
        if (!savedContext.site) {
          setSiteState(defaults.site);
        }
        if (!savedContext.user) {
          setUserState(defaults.user);
        }
      })
      .catch((err) => setError(err.message));
  }, [savedContext.site, savedContext.user]);

  useEffect(() => {
    localStorage.setItem(CONTEXT_KEY, JSON.stringify({ site, user }));
  }, [site, user]);

  const refreshGraph = useCallback(async () => {
    const data = await postJson<GraphData>("/graph-data", {
      ...payload,
      hierarchy: true,
      assoc_floor: assocFloor
    });
    setGraph(data);
  }, [assocFloor, payload]);

  const refreshSuggestions = useCallback(async () => {
    const data = await postJson<Suggestion[]>("/suggestions/list", {
      ...payload,
      refresh: true
    });
    setSuggestions(Array.isArray(data) ? data : []);
  }, [payload]);

  const refreshAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [graphData, cardData, suggestionData, recallData, auditData, replayData, healthData] = await Promise.all([
        postJson<GraphData>("/graph-data", { ...payload, hierarchy: true, assoc_floor: assocFloor }),
        postJson<PromptCard>("/card", { ...payload, context }),
        postJson<Suggestion[]>("/suggestions/list", { ...payload, refresh: true }),
        postJson<unknown[]>("/recall", { ...payload, limit: 40 }),
        postJson<unknown[]>("/audit", payload),
        postJson<RecallReplay>("/recall-replay", { ...payload, context }),
        getJson<Record<string, unknown>>("/health")
      ]);
      setGraph(graphData);
      setCard(cardData);
      setSuggestions(Array.isArray(suggestionData) ? suggestionData : []);
      setEvents(Array.isArray(recallData) ? recallData : []);
      setAudit(Array.isArray(auditData) ? auditData : []);
      setReplay(replayData);
      setHealth(healthData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [assocFloor, context, payload]);

  useEffect(() => {
    refreshAll();
  }, [refreshAll]);

  const acceptSuggestion = useCallback(async (suggestion: Suggestion) => {
    await postJson("/suggestions/accept", { ...payload, suggestion_id: suggestionId(suggestion) });
    await refreshAll();
  }, [payload, refreshAll]);

  const rejectSuggestion = useCallback(async (suggestion: Suggestion) => {
    await postJson("/suggestions/reject", { ...payload, suggestion_id: suggestionId(suggestion) });
    await refreshSuggestions();
  }, [payload, refreshSuggestions]);

  const editAttr = useCallback(async (attr: string, weight: number) => {
    await postJson("/edit", { ...payload, attr, weight });
    await refreshAll();
  }, [payload, refreshAll]);

  const forgetUser = useCallback(async () => {
    await postJson("/delete", payload);
    setGraph(null);
    setCard(null);
    setSuggestions([]);
    setEvents([]);
    setAudit([]);
    setReplay(null);
  }, [payload]);

  const value: FernState = {
    site,
    user,
    contextText,
    assocFloor,
    knownOnly,
    graph,
    card,
    suggestions,
    events,
    audit,
    replay,
    health,
    loading,
    error,
    setSite,
    setUser,
    setContextText,
    setAssocFloor,
    setKnownOnly,
    refreshAll,
    refreshGraph,
    refreshSuggestions,
    acceptSuggestion,
    rejectSuggestion,
    editAttr,
    forgetUser
  };

  return <FernContext.Provider value={value}>{children}</FernContext.Provider>;
}

export function useFern() {
  const value = useContext(FernContext);
  if (!value) {
    throw new Error("useFern must be used inside FernProvider");
  }
  return value;
}
