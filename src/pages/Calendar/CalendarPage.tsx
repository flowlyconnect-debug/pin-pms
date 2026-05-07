import FullCalendar from "@fullcalendar/react";
import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin from "@fullcalendar/interaction";
import fiLocale from "@fullcalendar/core/locales/fi";
import timeGridPlugin from "@fullcalendar/timegrid";
import type { EventClickArg, EventInput } from "@fullcalendar/core";
import "../../styles/fullcalendar-overrides.css";

type CalendarEventKind = "varaus" | "pidatys" | "huolto" | "konflikti";

type CalendarPageProps = {
  events?: EventInput[];
  openBookingModal?: (event: EventClickArg["event"]) => void;
};

const DEMO_EVENTS: EventInput[] = [
  { id: "1", title: "Varaus - Aalto", start: "2026-05-15", end: "2026-05-18", extendedProps: { kind: "varaus" } },
  { id: "2", title: "Pidätys - Niemi", start: "2026-05-17", end: "2026-05-19", extendedProps: { kind: "pidatys" } },
  { id: "3", title: "Huolto - Lämmitys", start: "2026-05-20T10:00:00", end: "2026-05-20T14:00:00", extendedProps: { kind: "huolto" } },
  { id: "4", title: "Konflikti - Tuplavaraus", start: "2026-05-18", end: "2026-05-19", extendedProps: { kind: "konflikti" } },
];

function toCalendarDate(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function CalendarPage({ events, openBookingModal }: CalendarPageProps) {
  const calendarEvents = events?.length ? events : DEMO_EVENTS;

  return (
    <section
      style={{
        border: "1px solid var(--border)",
        borderRadius: 12,
        background: "var(--surface)",
        padding: 16,
      }}
    >
      <header style={{ marginBottom: 12 }}>
        <h1 style={{ margin: 0, fontSize: 24 }}>Kalenteri</h1>
      </header>

      <FullCalendar
        plugins={[dayGridPlugin, timeGridPlugin, interactionPlugin]}
        initialView="dayGridMonth"
        locale={fiLocale}
        firstDay={1}
        weekNumbers
        navLinks
        editable
        selectable
        nowIndicator
        weekends
        events={calendarEvents}
        headerToolbar={{
          left: "prev,next today",
          center: "title",
          right: "dayGridMonth,timeGridWeek,timeGridDay",
        }}
        buttonText={{
          today: "Tänään",
          month: "Kuukausi",
          week: "Viikko",
          day: "Päivä",
        }}
        dateClick={(info) => {
          window.location.href = `/kalenteri/${info.dateStr}`;
        }}
        eventClick={(info) => {
          if (openBookingModal) {
            openBookingModal(info.event);
            return;
          }
          const dateStr = toCalendarDate(info.event.start ?? new Date());
          window.location.href = `/kalenteri/${dateStr}`;
        }}
        eventClassNames={(arg) => {
          const kind = arg.event.extendedProps.kind as CalendarEventKind | undefined;
          if (kind === "konflikti") return ["fc-event-danger"];
          if (kind === "pidatys") return ["fc-event-warning"];
          if (kind === "huolto") return ["fc-event-neutral"];
          return ["fc-event-info"];
        }}
        height="auto"
      />
    </section>
  );
}
