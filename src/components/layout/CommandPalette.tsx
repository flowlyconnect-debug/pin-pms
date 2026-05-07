import { type CSSProperties, type ReactNode, useEffect, useMemo, useState } from "react";
import { Command } from "cmdk";
import { FileText, Home, Search, Users, Building2, Receipt, CalendarPlus, UserPlus } from "lucide-react";

type PaletteItem = {
  id: string;
  label: string;
  keywords: string[];
  href?: string;
  onSelect?: () => void;
  icon?: ReactNode;
};

type CommandPaletteProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onNavigate?: (href: string) => void;
  onCreateInvoice?: () => void;
  onCreateReservation?: () => void;
  onCreateCustomer?: () => void;
  searchResults?: {
    customers?: Array<{ id: string; name: string }>;
    properties?: Array<{ id: string; name: string }>;
    invoices?: Array<{ id: string; code: string }>;
  };
};

const baseOverlayStyle: CSSProperties = {
  position: "fixed",
  inset: 0,
  background: "rgba(12, 10, 9, 0.38)",
  display: "grid",
  placeItems: "start center",
  paddingTop: "10vh",
  zIndex: 80,
};

const baseDialogStyle: CSSProperties = {
  width: "min(640px, calc(100vw - 32px))",
  borderRadius: 12,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  boxShadow: "var(--shadow-lg)",
  overflow: "hidden",
};

export function CommandPalette({
  open,
  onOpenChange,
  onNavigate,
  onCreateInvoice,
  onCreateReservation,
  onCreateCustomer,
  searchResults,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const isK = event.key.toLowerCase() === "k";
      if ((event.metaKey || event.ctrlKey) && isK) {
        event.preventDefault();
        onOpenChange(!open);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onOpenChange]);

  const goItems = useMemo<PaletteItem[]>(
    () => [
      { id: "go-home", label: "Mene -> Etusivu", keywords: ["etusivu", "dashboard"], href: "/" , icon: <Home size={14} />},
      { id: "go-properties", label: "Mene -> Kohteet", keywords: ["kohteet", "properties"], href: "/properties", icon: <Building2 size={14} /> },
      { id: "go-invoices", label: "Mene -> Laskut", keywords: ["laskut", "invoices"], href: "/invoices", icon: <Receipt size={14} /> },
      { id: "go-reservations", label: "Mene -> Varaukset", keywords: ["varaukset", "reservations"], href: "/reservations", icon: <FileText size={14} /> },
    ],
    []
  );

  const createItems = useMemo<PaletteItem[]>(
    () => [
      { id: "create-invoice", label: "Luo -> Uusi lasku", keywords: ["uusi", "lasku"], onSelect: onCreateInvoice, icon: <Receipt size={14} /> },
      { id: "create-reservation", label: "Luo -> Uusi varaus", keywords: ["uusi", "varaus"], onSelect: onCreateReservation, icon: <CalendarPlus size={14} /> },
      { id: "create-customer", label: "Luo -> Uusi asiakas", keywords: ["uusi", "asiakas"], onSelect: onCreateCustomer, icon: <UserPlus size={14} /> },
    ],
    [onCreateCustomer, onCreateInvoice, onCreateReservation]
  );

  const backendItems = useMemo<PaletteItem[]>(() => {
    const customers =
      searchResults?.customers?.map((item) => ({
        id: `customer-${item.id}`,
        label: `Asiakas -> ${item.name}`,
        keywords: ["asiakas", item.name.toLowerCase()],
        href: `/customers/${item.id}`,
        icon: <Users size={14} />,
      })) ?? [];
    const properties =
      searchResults?.properties?.map((item) => ({
        id: `property-${item.id}`,
        label: `Kohde -> ${item.name}`,
        keywords: ["kohde", item.name.toLowerCase()],
        href: `/properties/${item.id}`,
        icon: <Building2 size={14} />,
      })) ?? [];
    const invoices =
      searchResults?.invoices?.map((item) => ({
        id: `invoice-${item.id}`,
        label: `Lasku -> ${item.code}`,
        keywords: ["lasku", item.code.toLowerCase()],
        href: `/invoices/${item.id}`,
        icon: <Receipt size={14} />,
      })) ?? [];

    return [...customers, ...properties, ...invoices];
  }, [searchResults]);

  const handleItemSelect = (item: PaletteItem) => {
    if (item.onSelect) {
      item.onSelect();
    }
    if (item.href && onNavigate) {
      onNavigate(item.href);
    }
    onOpenChange(false);
    setQuery("");
  };

  if (!open) {
    return null;
  }

  return (
    <div style={baseOverlayStyle} onClick={() => onOpenChange(false)}>
      <Command
        label="Command palette"
        shouldFilter
        style={baseDialogStyle}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            borderBottom: "1px solid var(--border)",
            padding: "10px 12px",
          }}
        >
          <Search size={14} color="var(--text-soft)" />
          <Command.Input
            value={query}
            onValueChange={setQuery}
            placeholder="Hae varauksia, asiakkaita, laskuja..."
            style={{
              border: 0,
              outline: "none",
              background: "transparent",
              width: "100%",
              fontSize: 14,
              color: "var(--text)",
            }}
          />
        </div>
        <Command.List style={{ maxHeight: 360, overflow: "auto", padding: 8 }}>
          <Command.Empty style={{ padding: 10, color: "var(--text-soft)", fontSize: 13 }}>
            Ei tuloksia.
          </Command.Empty>

          <Command.Group heading="Mene" style={{ padding: 4, fontSize: 12, color: "var(--text-soft)" }}>
            {goItems.map((item) => (
              <Command.Item
                key={item.id}
                value={[item.label, ...item.keywords].join(" ")}
                onSelect={() => handleItemSelect(item)}
                style={itemStyle}
              >
                {item.icon}
                <span>{item.label}</span>
              </Command.Item>
            ))}
          </Command.Group>

          <Command.Group heading="Luo" style={{ padding: 4, fontSize: 12, color: "var(--text-soft)" }}>
            {createItems.map((item) => (
              <Command.Item
                key={item.id}
                value={[item.label, ...item.keywords].join(" ")}
                onSelect={() => handleItemSelect(item)}
                style={itemStyle}
              >
                {item.icon}
                <span>{item.label}</span>
              </Command.Item>
            ))}
          </Command.Group>

          {backendItems.length > 0 && (
            <Command.Group heading="Hakuosumat" style={{ padding: 4, fontSize: 12, color: "var(--text-soft)" }}>
              {backendItems.map((item) => (
                <Command.Item
                  key={item.id}
                  value={[item.label, ...item.keywords].join(" ")}
                  onSelect={() => handleItemSelect(item)}
                  style={itemStyle}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </Command.Item>
              ))}
            </Command.Group>
          )}
        </Command.List>
      </Command>
    </div>
  );
}

const itemStyle: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 10,
  fontSize: 14,
  padding: "10px 10px",
  borderRadius: 8,
  color: "var(--text)",
  cursor: "pointer",
};
