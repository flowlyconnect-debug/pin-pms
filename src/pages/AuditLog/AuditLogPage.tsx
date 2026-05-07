import { useEffect, useMemo, useState } from "react";
import { Download, Funnel, RefreshCw } from "lucide-react";

type AuditEventDiff = {
  field: string;
  oldValue: string | null;
  newValue: string | null;
};

type AuditEvent = {
  id: number;
  created_at: string;
  action: string;
  action_label: string;
  action_type: string;
  actor_id: number | null;
  actor_name: string;
  actor_email: string | null;
  actor_avatar: string | null;
  entity_type: string;
  entity_label: string;
  entity_id: number | null;
  entity_ref: string | null;
  entity_url: string | null;
  summary: string;
  time_label: string;
  diff: AuditEventDiff[];
};

type AuditResponse = {
  events: AuditEvent[];
  page: number;
  has_next: boolean;
  users: Array<{ id: number; name: string; avatar: string | null }>;
  actions: Array<{ key: string; label: string }>;
  entities: Array<{ key: string; label: string }>;
};

type RelativeRange = "today" | "7d" | "30d" | "custom";

const DEFAULT_ACTIONS = [
  { key: "create", label: "Luotu" },
  { key: "update", label: "Muokattu" },
  { key: "delete", label: "Poistettu" },
  { key: "login", label: "Login" },
  { key: "send", label: "Lähetetty" },
];

const DEFAULT_ENTITIES = [
  { key: "invoice", label: "Lasku" },
  { key: "customer", label: "Asiakas" },
  { key: "contract", label: "Sopimus" },
  { key: "property", label: "Kohde" },
  { key: "user", label: "Käyttäjä" },
];

const ACTION_COLORS: Record<string, string> = {
  create: "#16A34A",
  update: "#2563EB",
  delete: "#DC2626",
  login: "#7C3AED",
  send: "#EA580C",
};

function parseMulti(search: URLSearchParams, key: string): string[] {
  return search
    .getAll(key)
    .flatMap((value) => value.split(","))
    .map((value) => value.trim())
    .filter(Boolean);
}

function toDateInputValue(input: Date): string {
  return input.toISOString().slice(0, 10);
}

function getDefaultRange(range: RelativeRange): { from: string; to: string } {
  const now = new Date();
  const to = new Date(now);
  const from = new Date(now);
  if (range === "7d") {
    from.setDate(from.getDate() - 6);
  } else if (range === "30d") {
    from.setDate(from.getDate() - 29);
  }
  return { from: toDateInputValue(from), to: toDateInputValue(to) };
}

function formatDayHeader(dateString: string): string {
  const date = new Date(dateString);
  const today = new Date();
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  const sameDay =
    date.getDate() === today.getDate() &&
    date.getMonth() === today.getMonth() &&
    date.getFullYear() === today.getFullYear();
  const sameYesterday =
    date.getDate() === yesterday.getDate() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getFullYear() === yesterday.getFullYear();
  const formatter = new Intl.DateTimeFormat("fi-FI", { dateStyle: "short" });
  if (sameDay) return `Tänään, ${formatter.format(date)}`;
  if (sameYesterday) return `Eilen, ${formatter.format(date)}`;
  return formatter.format(date);
}

function groupByDay(events: AuditEvent[]) {
  const groups = new Map<string, AuditEvent[]>();
  for (const event of events) {
    const dayKey = event.created_at.slice(0, 10);
    const current = groups.get(dayKey) ?? [];
    current.push(event);
    groups.set(dayKey, current);
  }
  return Array.from(groups.entries()).map(([day, dayEvents]) => ({ day, events: dayEvents }));
}

export function AuditLogPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [users, setUsers] = useState<Array<{ id: number; name: string; avatar: string | null }>>([]);
  const [actions, setActions] = useState(DEFAULT_ACTIONS);
  const [entities, setEntities] = useState(DEFAULT_ENTITIES);
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [newEventToastVisible, setNewEventToastVisible] = useState(false);

  const initialFilters = useMemo(() => {
    const search = new URLSearchParams(window.location.search);
    const from = search.get("from");
    const to = search.get("to");
    const range = (search.get("range") as RelativeRange) || "7d";
    const defaults = getDefaultRange(range === "custom" ? "7d" : range);
    return {
      range,
      from: from ?? defaults.from,
      to: to ?? defaults.to,
      users: parseMulti(search, "user"),
      actions: parseMulti(search, "action"),
      entities: parseMulti(search, "entity"),
      page: Number(search.get("page") || "1"),
    };
  }, []);

  const [range, setRange] = useState<RelativeRange>(initialFilters.range);
  const [from, setFrom] = useState(initialFilters.from);
  const [to, setTo] = useState(initialFilters.to);
  const [selectedUsers, setSelectedUsers] = useState<string[]>(initialFilters.users);
  const [selectedActions, setSelectedActions] = useState<string[]>(initialFilters.actions);
  const [selectedEntities, setSelectedEntities] = useState<string[]>(initialFilters.entities);
  const [page, setPage] = useState<number>(Number.isFinite(initialFilters.page) ? initialFilters.page : 1);
  const [hasNext, setHasNext] = useState(false);

  const queryString = useMemo(() => {
    const search = new URLSearchParams();
    search.set("from", from);
    search.set("to", to);
    search.set("range", range);
    for (const user of selectedUsers) search.append("user", user);
    for (const action of selectedActions) search.append("action", action);
    for (const entity of selectedEntities) search.append("entity", entity);
    search.set("page", String(page));
    return search.toString();
  }, [from, page, range, selectedActions, selectedEntities, selectedUsers, to]);

  useEffect(() => {
    const url = `${window.location.pathname}?${queryString}`;
    window.history.replaceState({}, "", url);
  }, [queryString]);

  useEffect(() => {
    const controller = new AbortController();
    async function loadEvents() {
      setLoading(true);
      try {
        const response = await fetch(`/api/audit-events?${queryString}`, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
          credentials: "same-origin",
        });
        if (!response.ok) return;
        const payload = (await response.json()) as AuditResponse;
        setEvents(payload.events ?? []);
        setHasNext(Boolean(payload.has_next));
        if (Array.isArray(payload.users)) setUsers(payload.users);
        if (Array.isArray(payload.actions) && payload.actions.length) setActions(payload.actions);
        if (Array.isArray(payload.entities) && payload.entities.length) setEntities(payload.entities);
      } finally {
        setLoading(false);
      }
    }
    loadEvents();
    return () => controller.abort();
  }, [queryString]);

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    const live = new EventSource("/api/audit-events/stream", { withCredentials: true });
    live.addEventListener("message", () => {
      setNewEventToastVisible(true);
    });
    live.addEventListener("error", () => live.close());
    return () => live.close();
  }, []);

  const dayGroups = useMemo(() => groupByDay(events), [events]);

  const clearFilters = () => {
    const defaults = getDefaultRange("7d");
    setRange("7d");
    setFrom(defaults.from);
    setTo(defaults.to);
    setSelectedUsers([]);
    setSelectedActions([]);
    setSelectedEntities([]);
    setPage(1);
  };

  const toggleSelected = (current: string[], value: string, setter: (next: string[]) => void) => {
    const exists = current.includes(value);
    setter(exists ? current.filter((item) => item !== value) : [...current, value]);
    setPage(1);
  };

  return (
    <div style={{ display: "grid", gridTemplateColumns: "320px 1fr", gap: 24, alignItems: "start" }}>
      <aside
        style={{
          position: "sticky",
          top: 16,
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "var(--surface)",
          padding: 16,
          display: "grid",
          gap: 16,
          minHeight: "calc(100vh - 140px)",
        }}
      >
        <h2 style={{ margin: 0, fontSize: 17, display: "flex", alignItems: "center", gap: 8 }}>
          <Funnel size={16} /> Suodattimet
        </h2>
        <section style={{ display: "grid", gap: 8 }}>
          <strong style={{ fontSize: 13 }}>Aikaväli</strong>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
            {[
              { key: "today", label: "Tänään" },
              { key: "7d", label: "7 pv" },
              { key: "30d", label: "30 pv" },
              { key: "custom", label: "Custom range" },
            ].map((item) => (
              <button
                key={item.key}
                type="button"
                data-variant={range === item.key ? "primary" : "secondary"}
                onClick={() => {
                  const next = item.key as RelativeRange;
                  setRange(next);
                  if (next !== "custom") {
                    const defaults = getDefaultRange(next);
                    setFrom(defaults.from);
                    setTo(defaults.to);
                  }
                  setPage(1);
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
          {range === "custom" ? (
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
              <input type="date" value={from} onChange={(event) => setFrom(event.target.value)} />
              <input type="date" value={to} onChange={(event) => setTo(event.target.value)} />
            </div>
          ) : null}
        </section>

        <FilterList
          title="Käyttäjä"
          items={users.map((user) => ({
            value: String(user.id),
            label: user.name,
            avatar: user.avatar,
          }))}
          selected={selectedUsers}
          onToggle={(value) => toggleSelected(selectedUsers, value, setSelectedUsers)}
        />

        <FilterList
          title="Toiminto"
          items={actions.map((action) => ({ value: action.key, label: action.label }))}
          selected={selectedActions}
          onToggle={(value) => toggleSelected(selectedActions, value, setSelectedActions)}
        />

        <FilterList
          title="Kohde"
          items={entities.map((entity) => ({ value: entity.key, label: entity.label }))}
          selected={selectedEntities}
          onToggle={(value) => toggleSelected(selectedEntities, value, setSelectedEntities)}
        />

        <button type="button" data-variant="ghost" style={{ marginTop: "auto", justifySelf: "start" }} onClick={clearFilters}>
          Tyhjennä suodattimet
        </button>
      </aside>

      <section style={{ border: "1px solid var(--border)", borderRadius: 12, background: "var(--surface)", padding: 20 }}>
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <h1 style={{ margin: 0, fontSize: 24 }}>Audit-loki</h1>
          <a href={`/api/audit-events?${queryString}&format=csv`} data-variant="secondary" style={{ textDecoration: "none" }}>
            <Download size={15} /> CSV-export
          </a>
        </header>

        {newEventToastVisible ? (
          <button
            type="button"
            data-variant="secondary"
            style={{ marginBottom: 14 }}
            onClick={() => {
              setNewEventToastVisible(false);
              setPage(1);
            }}
          >
            <RefreshCw size={14} /> Uusi tapahtuma
          </button>
        ) : null}

        {loading ? <p style={{ color: "var(--text-muted)" }}>Ladataan tapahtumia...</p> : null}

        <div style={{ position: "relative", borderLeft: "2px solid rgba(120, 113, 108, 0.35)", paddingLeft: 22 }}>
          {dayGroups.map((group) => (
            <article key={group.day} style={{ marginBottom: 22 }}>
              <h3 style={{ margin: "0 0 10px 0", color: "var(--text-muted)", fontSize: 13 }}>{formatDayHeader(group.day)}</h3>
              <div style={{ display: "grid", gap: 10 }}>
                {group.events.map((event) => {
                  const isExpanded = Boolean(expanded[event.id]);
                  return (
                    <div key={event.id} style={{ position: "relative", borderRadius: 10, padding: "8px 10px", background: "var(--surface)" }}>
                      <span
                        aria-hidden
                        style={{
                          width: 11,
                          height: 11,
                          borderRadius: "50%",
                          background: ACTION_COLORS[event.action_type] ?? "var(--text-soft)",
                          position: "absolute",
                          left: -28,
                          top: 16,
                        }}
                      />
                      <div style={{ display: "grid", gridTemplateColumns: "24px 1fr auto", gap: 10, alignItems: "center" }}>
                        <Avatar name={event.actor_name} src={event.actor_avatar} />
                        <a href={event.entity_url ?? "#"} style={{ color: "var(--text)", textDecoration: "none", fontSize: 14 }}>
                          {event.summary}
                        </a>
                        <span style={{ color: "var(--text-soft)", fontSize: 12 }}>{event.time_label}</span>
                      </div>
                      <button
                        type="button"
                        data-variant="ghost"
                        style={{ padding: "6px 0", fontSize: 12 }}
                        onClick={() => setExpanded((prev) => ({ ...prev, [event.id]: !prev[event.id] }))}
                      >
                        {isExpanded ? "Piilota yksityiskohdat" : "Näytä yksityiskohdat"}
                      </button>
                      {isExpanded ? (
                        <div
                          style={{
                            marginTop: 6,
                            background: "var(--bg-alt)",
                            borderRadius: 8,
                            padding: 12,
                            fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace",
                            fontSize: 12,
                            display: "grid",
                            gap: 4,
                          }}
                        >
                          {event.diff.length ? (
                            event.diff.map((change) => (
                              <div key={`${event.id}-${change.field}`}>
                                {change.field}: {change.oldValue ?? "-"} -> {change.newValue ?? "-"}
                              </div>
                            ))
                          ) : (
                            <div>Ei kenttämuutoksia.</div>
                          )}
                        </div>
                      ) : null}
                    </div>
                  );
                })}
              </div>
            </article>
          ))}
          {!loading && !events.length ? <p style={{ color: "var(--text-muted)" }}>Ei tapahtumia valituilla suodattimilla.</p> : null}
        </div>

        <footer style={{ display: "flex", justifyContent: "space-between", marginTop: 16 }}>
          <button type="button" data-variant="secondary" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
            Edellinen
          </button>
          <span style={{ color: "var(--text-muted)", alignSelf: "center" }}>Sivu {page}</span>
          <button type="button" data-variant="secondary" disabled={!hasNext} onClick={() => setPage((value) => value + 1)}>
            Seuraava
          </button>
        </footer>
      </section>
    </div>
  );
}

function Avatar({ name, src }: { name: string; src: string | null }) {
  const initials = name
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
  return (
    <span
      style={{
        width: 24,
        height: 24,
        borderRadius: "50%",
        overflow: "hidden",
        display: "inline-grid",
        placeItems: "center",
        background: "var(--bg-alt)",
        color: "var(--text-muted)",
        fontSize: 11,
        border: "1px solid var(--border)",
      }}
      title={name}
    >
      {src ? <img src={src} alt={name} style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : initials || "?"}
    </span>
  );
}

function FilterList({
  title,
  items,
  selected,
  onToggle,
}: {
  title: string;
  items: Array<{ value: string; label: string; avatar?: string | null }>;
  selected: string[];
  onToggle: (value: string) => void;
}) {
  return (
    <section style={{ display: "grid", gap: 8 }}>
      <strong style={{ fontSize: 13 }}>{title}</strong>
      <div style={{ display: "grid", gap: 4, maxHeight: 190, overflow: "auto", paddingRight: 4 }}>
        {items.map((item) => {
          const checked = selected.includes(item.value);
          return (
            <label key={item.value} style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14, cursor: "pointer" }}>
              <input type="checkbox" checked={checked} onChange={() => onToggle(item.value)} />
              {item.avatar ? <Avatar name={item.label} src={item.avatar} /> : null}
              <span>{item.label}</span>
            </label>
          );
        })}
        {!items.length ? <span style={{ color: "var(--text-soft)", fontSize: 12 }}>Ei vaihtoehtoja.</span> : null}
      </div>
    </section>
  );
}
