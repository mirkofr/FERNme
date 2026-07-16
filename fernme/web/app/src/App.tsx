import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import {
  Activity,
  Check,
  ChevronDown,
  Code2,
  FileJson,
  Gauge,
  Inbox,
  ListFilter,
  RefreshCw,
  ScrollText,
  ShieldCheck,
  UserRound,
  X
} from "lucide-react";
import logoUrl from "./assets/logo.png";
import GraphView from "./GraphView";
import { PromptCard, Suggestion } from "./api";
import { useFern } from "./store";

type JsonRecord = Record<string, unknown>;

function Shell() {
  const fern = useFern();
  return (
    <div className="fern-app">
      <header className="topbar">
        <div className="brand" aria-label="FERNme">
          <span className="brand__mark"><img src={logoUrl} alt="" aria-hidden="true" /></span>
          <strong className="brand__name">FERNme</strong>
        </div>
        <nav className="primary-nav" aria-label="Main views">
          <NavLink className="primary-nav__item" to="/graph">Graph</NavLink>
          <NavLink className="primary-nav__item" to="/review">Review queue</NavLink>
          <NavLink className="primary-nav__item" to="/editor">Memory editor</NavLink>
          <NavLink className="primary-nav__item" to="/feed">Feed</NavLink>
          <NavLink className="primary-nav__item" to="/health">Health</NavLink>
        </nav>
        <div className="topbar__context">
          <label className="select-control context-input">
            <span className="icon"><UserRound aria-hidden="true" /></span>
            <input aria-label="Site" value={fern.site} onChange={(event) => fern.setSite(event.target.value)} />
            <ChevronDown className="select-control__chevron" aria-hidden="true" />
          </label>
          <label className="select-control context-input">
            <span className="icon"><UserRound aria-hidden="true" /></span>
            <input aria-label="User" value={fern.user} onChange={(event) => fern.setUser(event.target.value)} />
            <ChevronDown className="select-control__chevron" aria-hidden="true" />
          </label>
          <label className="select-control context-input context-input--wide">
            <span className="icon"><ListFilter aria-hidden="true" /></span>
            <input
              aria-label="Recall seed"
              placeholder="recall seed"
              title="Comma-separated memory attributes used by recall and graph focus."
              value={fern.contextText}
              onChange={(event) => fern.setContextText(event.target.value)}
            />
            <ChevronDown className="select-control__chevron" aria-hidden="true" />
          </label>
          <button type="button" className="button button--primary" onClick={fern.refreshAll} disabled={fern.loading}>
            Load
          </button>
        </div>
      </header>
      {fern.error ? <div className="status-strip error">{fern.error}</div> : null}
      <main className="route-shell">
        <Routes>
          <Route path="/" element={<Navigate to="/graph" replace />} />
          <Route path="/graph" element={<GraphView />} />
          <Route path="/review" element={<ReviewQueue />} />
          <Route path="/editor" element={<MemoryEditor />} />
          <Route path="/feed" element={<FeedView />} />
          <Route path="/health" element={<HealthView />} />
        </Routes>
      </main>
    </div>
  );
}

function ReviewQueue() {
  const fern = useFern();
  return (
    <PageShell>
      <PageHeader
        icon={<Inbox aria-hidden="true" />}
        title="Review queue"
        count={fern.suggestions.length}
        actionLabel="Refresh"
        onAction={fern.refreshSuggestions}
      />
      {fern.suggestions.length === 0 ? (
        <EmptyState text="No pending suggestions for this context." />
      ) : (
        <div className="review-grid">
          {fern.suggestions.map((suggestion, index) => (
            <SuggestionCard
              key={`${suggestion.suggestion_id || suggestion.id || index}`}
              suggestion={suggestion}
              onAccept={() => fern.acceptSuggestion(suggestion)}
              onReject={() => fern.rejectSuggestion(suggestion)}
            />
          ))}
        </div>
      )}
    </PageShell>
  );
}

function MemoryEditor() {
  const fern = useFern();
  const links = fern.card?.links || [];
  return (
    <PageShell split>
      <section className="page-column">
        <PageHeader
          icon={<ScrollText aria-hidden="true" />}
          title="Prompt card"
          count={links.length}
          actionLabel="Refresh"
          onAction={fern.refreshAll}
        />
        {links.length === 0 ? (
          <EmptyState text="No card links are available yet." />
        ) : (
          <div className="editor-list">
            {links.map((link) => (
              <article className="memory-row" key={link.attr}>
                <div className="row-main">
                  <span className="row-kicker">{attrNamespace(link.attr) || "attr"}</span>
                  <h2>{displayAttr(link.attr)}</h2>
                  <p>confidence {formatMetric(link.confidence)} - source {link.source || "n/a"}</p>
                </div>
                <input
                  aria-label={`Weight for ${link.attr}`}
                  type="number"
                  min="0"
                  max="9"
                  defaultValue={link.weight || 0}
                  onBlur={(event) => fern.editAttr(link.attr, Number(event.target.value))}
                />
              </article>
            ))}
          </div>
        )}
      </section>
      <SidePanel icon={<FileJson aria-hidden="true" />} title="Export">
        <CardSummary card={fern.card} />
        <PromptCardView card={fern.card} />
        <RawDetails data={fern.card || {}} />
        <button type="button" className="button button--danger" onClick={fern.forgetUser}>Forget this user</button>
      </SidePanel>
    </PageShell>
  );
}

function FeedView() {
  const fern = useFern();
  return (
    <PageShell split>
      <section className="page-column">
        <PageHeader
          icon={<Activity aria-hidden="true" />}
          title="Feed"
          count={fern.events.length}
          actionLabel="Refresh"
          onAction={fern.refreshAll}
        />
        <EventRows rows={fern.events} empty="No recalled events for this context." />
      </section>
      <SidePanel icon={<ShieldCheck aria-hidden="true" />} title="Audit">
        <EventRows rows={fern.audit} empty="No audit records returned." compact />
      </SidePanel>
    </PageShell>
  );
}

function HealthView() {
  const fern = useFern();
  return (
    <PageShell split>
      <section className="page-column">
        <PageHeader
          icon={<Gauge aria-hidden="true" />}
          title="Health"
          count={fern.suggestions.length}
          actionLabel="Refresh"
          onAction={fern.refreshAll}
        />
        <div className="metric-grid">
          <Metric label="API" value={String(fern.health?.ok ?? false)} />
          <Metric label="Visible nodes" value={String(fern.graph?.nodes?.length || 0)} />
          <Metric label="Visible links" value={String(fern.graph?.edges?.length || 0)} />
          <Metric label="Pending review" value={String(fern.suggestions.length)} />
        </div>
        <section className="replay">
          <h2>Recall replay</h2>
          {fern.replay?.steps?.length ? (
            <div className="editor-list">
              {fern.replay.steps.slice(0, 16).map((step) => (
                <article className="memory-row" key={step.attr}>
                  <div className="row-main">
                    <span className="row-kicker">{attrNamespace(step.attr) || "trace"}</span>
                    <h2>{displayAttr(step.attr)}</h2>
                    <p>activation {formatMetric(step.activation)} - weight {step.weight} - confidence {formatMetric(step.confidence)}</p>
                  </div>
                  <span className={step.in_card ? "pill ok" : "pill"}>{step.in_card ? "in card" : "trace"}</span>
                </article>
              ))}
            </div>
          ) : (
            <EmptyState text="No replay steps for the current recall context." />
          )}
        </section>
      </section>
      <SidePanel icon={<FileJson aria-hidden="true" />} title="Card output">
        <CardSummary card={fern.card} />
        <PromptCardView card={fern.card} />
        <RawDetails data={fern.card || {}} />
      </SidePanel>
    </PageShell>
  );
}

function SuggestionCard({
  suggestion,
  onAccept,
  onReject
}: {
  suggestion: Suggestion;
  onAccept: () => void;
  onReject: () => void;
}) {
  const payload = asRecord(suggestion.payload || suggestion);
  const title = suggestionTitle(suggestion, payload);
  const source = String(payload.source || suggestion.kind || "suggestion");
  const kind = String(payload.entity_kind || suggestion.kind || "review");
  return (
    <article className="review-card">
      <div className="row-main">
        <span className="row-kicker">{titleCase(String(suggestion.kind || "suggestion"))}</span>
        <h2>{title}</h2>
        <p>{titleCase(kind)} - {source}</p>
      </div>
      <PayloadSummary payload={payload} />
      <div className="row-actions">
        <button type="button" className="button button--primary" onClick={onAccept}><Check className="icon" aria-hidden="true" /> Accept</button>
        <button type="button" className="button" onClick={onReject}><X className="icon" aria-hidden="true" /> Reject</button>
      </div>
      <RawDetails data={payload} compact />
    </article>
  );
}

function PageShell({ children, split = false }: { children: React.ReactNode; split?: boolean }) {
  return <section className={split ? "view-pad page-shell page-shell--split" : "view-pad page-shell"}>{children}</section>;
}

function PageHeader({
  icon,
  title,
  count,
  actionLabel,
  onAction
}: {
  icon: React.ReactNode;
  title: string;
  count?: number;
  actionLabel: string;
  onAction: () => void;
}) {
  return (
    <div className="page-header">
      <div className="page-title">
        <span className="page-title__icon">{icon}</span>
        <h1>{title}</h1>
        {count !== undefined ? <span className="count">{count}</span> : null}
      </div>
      <button type="button" className="button" onClick={onAction}><RefreshCw className="icon" aria-hidden="true" /> {actionLabel}</button>
    </div>
  );
}

function SidePanel({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <aside className="side-panel">
      <div className="side-panel__header">
        <span className="page-title__icon">{icon}</span>
        <h2>{title}</h2>
      </div>
      {children}
    </aside>
  );
}

function CardSummary({ card }: { card: PromptCard | null }) {
  const links = card?.links || [];
  return (
    <div className="mini-metrics">
      <Metric label="Links" value={String(links.length)} compact />
      <Metric label="Tokens" value={String(card?.tokens ?? "n/a")} compact />
    </div>
  );
}

function PromptCardView({ card }: { card: PromptCard | null }) {
  const links = card?.links || [];
  const wire = typeof card?.wire === "string" ? card.wire : "";
  if (!links.length && !wire) {
    return <EmptyState text="No card content for this context." />;
  }
  return (
    <div className="pretty-block">
      {wire ? (
        <section className="wire-panel">
          <span className="row-kicker">Wire</span>
          <p>{wire}</p>
        </section>
      ) : null}
      <div className="link-chip-grid">
        {links.slice(0, 18).map((link) => (
          <div className="link-chip-card" key={link.attr}>
            <span className="row-kicker">{attrNamespace(link.attr) || "attr"}</span>
            <strong>{displayAttr(link.attr)}</strong>
            <small>w {link.weight ?? "n/a"} - {link.known ? "known" : "observed"}</small>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="empty-state">{text}</div>;
}

function EventRows({ rows, empty, compact = false }: { rows: unknown[]; empty: string; compact?: boolean }) {
  if (!rows.length) {
    return <EmptyState text={empty} />;
  }
  return (
    <div className={compact ? "event-list event-list--compact" : "event-list"}>
      {rows.map((row, index) => (
        <article className="event-card" key={index}>
          <div className="row-main">
            <span className="row-kicker">{eventType(row)}</span>
            <h2>{eventTitle(row)}</h2>
            <p>{eventMeta(row)}</p>
          </div>
          <EventSummary row={row} compact={compact} />
          <RawDetails data={row} compact />
        </article>
      ))}
    </div>
  );
}

function Metric({ label, value, compact = false }: { label: string; value: string; compact?: boolean }) {
  return (
    <div className={compact ? "metric metric--compact" : "metric"}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PayloadSummary({ payload }: { payload: JsonRecord }) {
  const entries = Object.entries(payload)
    .filter(([, value]) => value !== undefined && value !== null && !Array.isArray(value) && typeof value !== "object")
    .slice(0, 8);
  const tags = toStringArray(payload.tags);
  return (
    <div className="payload-summary">
      {entries.map(([key, value]) => (
        <div className="kv" key={key}>
          <span>{titleCase(key)}</span>
          <strong>{String(value)}</strong>
        </div>
      ))}
      {tags.length ? <ChipList label="Tags" values={tags} /> : null}
    </div>
  );
}

function EventSummary({ row, compact = false }: { row: unknown; compact?: boolean }) {
  const record = asRecord(row);
  const payload = asRecord(record.payload);
  const tags = toStringArray(payload.tags);
  const attrs = Array.isArray(record.attrs)
    ? record.attrs.map((item) => Array.isArray(item) ? String(item[0]) : String(item)).slice(0, compact ? 4 : 8)
    : [];
  const text = typeof payload.text === "string" ? payload.text : "";
  return (
    <div className="event-summary">
      {text ? <p className="event-text">{text}</p> : null}
      {tags.length ? <ChipList label="Tags" values={tags} /> : null}
      {attrs.length ? <ChipList label="Attrs" values={attrs} /> : null}
      {!text && !tags.length && !attrs.length ? <PayloadSummary payload={record} /> : null}
    </div>
  );
}

function ChipList({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="chip-section">
      <span>{label}</span>
      <div className="chip-list">
        {values.slice(0, 18).map((value) => (
          <span className="data-chip" title={value} key={value}>{displayAttr(value)}</span>
        ))}
      </div>
    </div>
  );
}

function RawDetails({ data, compact = false }: { data: unknown; compact?: boolean }) {
  return (
    <details className={compact ? "raw-details raw-details--compact" : "raw-details"}>
      <summary><Code2 className="icon" aria-hidden="true" /> Raw</summary>
      <pre className={compact ? "json-block json-block--compact" : "json-block"}>{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

function asRecord(value: unknown): JsonRecord {
  return value && typeof value === "object" && !Array.isArray(value) ? value as JsonRecord : {};
}

function attrNamespace(value: unknown): string {
  const text = String(value || "");
  const body = text.startsWith("!") ? text.slice(1) : text;
  const colon = body.indexOf(":");
  return colon > 0 ? body.slice(0, colon) : "";
}

function displayAttr(value: unknown): string {
  const text = String(value || "n/a");
  const negative = text.startsWith("!") ? "!" : "";
  const body = negative ? text.slice(1) : text;
  const colon = body.indexOf(":");
  return colon > 0 ? `${negative}${body.slice(colon + 1)}` : text;
}

function titleCase(value: string): string {
  return value
    .split(/[-_\s:]+/)
    .filter(Boolean)
    .map((part) => `${part.slice(0, 1).toUpperCase()}${part.slice(1)}`)
    .join(" ");
}

function formatMetric(value: unknown): string {
  return typeof value === "number" ? value.toFixed(value >= 10 ? 2 : 3).replace(/0+$/, "").replace(/\.$/, "") : "n/a";
}

function suggestionTitle(suggestion: Suggestion, payload: JsonRecord): string {
  const direct = payload.display_name || payload.canonical_attr || payload.alias_attr || suggestion.id || suggestion.suggestion_id;
  return displayAttr(direct || suggestion.kind || "Suggestion");
}

function eventType(row: unknown): string {
  const record = asRecord(row);
  return titleCase(String(record.type || record.action || "record"));
}

function eventTitle(row: unknown): string {
  const record = asRecord(row);
  const payload = asRecord(record.payload);
  const firstAttr = Array.isArray(record.attrs) ? record.attrs[0] : undefined;
  const firstTag = Array.isArray(payload.tags) ? payload.tags[0] : undefined;
  const attrName = Array.isArray(firstAttr) ? firstAttr[0] : firstAttr;
  return displayAttr(attrName || firstTag || record.attr || record.hash || "Memory record");
}

function eventMeta(row: unknown): string {
  const record = asRecord(row);
  const payload = asRecord(record.payload);
  const source = payload.source || record.source || record.action || "local";
  const ts = record.ts !== undefined ? `ts ${String(record.ts)}` : "stored";
  return `${String(source)} - ${ts}`;
}

function toStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

export default function App() {
  return <Shell />;
}
