type DayEventType = "saapuminen" | "lahto" | "huolto";

type DayEvent = {
  id: string;
  time: string;
  title: string;
  unit: string;
  type: DayEventType;
};

type CalendarDayPageProps = {
  date: string;
  events?: DayEvent[];
};

const TYPE_COLORS: Record<DayEventType, string> = {
  saapuminen: "var(--info)",
  lahto: "var(--warning)",
  huolto: "var(--text-muted)",
};

const DEMO_DAY_EVENTS: DayEvent[] = [
  { id: "e1", time: "09:00", title: "Saapuminen: Virtanen", unit: "A1", type: "saapuminen" },
  { id: "e2", time: "11:30", title: "Lähtö: Miettinen", unit: "B2", type: "lahto" },
  { id: "e3", time: "14:00", title: "Huolto: Ilmastointi", unit: "C3", type: "huolto" },
];

export function CalendarDayPage({ date, events }: CalendarDayPageProps) {
  const dayEvents = events?.length ? events : DEMO_DAY_EVENTS;

  return (
    <section style={{ display: "grid", gap: 16 }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 24 }}>Päivän tapahtumat</h1>
          <p style={{ margin: "6px 0 0", color: "var(--text-muted)" }}>{date}</p>
        </div>
        <button type="button" data-variant="primary">
          Uusi varaus tälle päivälle
        </button>
      </header>

      <div
        style={{
          border: "1px solid var(--border)",
          borderRadius: 12,
          background: "var(--surface)",
          padding: 16,
          display: "grid",
          gridTemplateColumns: "88px 1fr",
          gap: 12,
        }}
      >
        <aside style={{ borderRight: "1px solid var(--border)", paddingRight: 12 }}>
          <strong style={{ display: "block", marginBottom: 8 }}>Aikajana</strong>
          <div style={{ display: "grid", gap: 6, color: "var(--text-soft)", fontSize: 12 }}>
            <span>00:00</span>
            <span>06:00</span>
            <span>12:00</span>
            <span>18:00</span>
            <span>23:59</span>
          </div>
        </aside>

        <div style={{ display: "grid", gap: 8 }}>
          {dayEvents.map((event) => (
            <article
              key={event.id}
              style={{
                border: "1px solid var(--border)",
                borderLeft: `4px solid ${TYPE_COLORS[event.type]}`,
                borderRadius: 8,
                padding: 10,
              }}
            >
              <strong>{event.time}</strong> - {event.title} ({event.unit})
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}
