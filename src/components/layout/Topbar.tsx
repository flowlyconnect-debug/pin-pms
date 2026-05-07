import { type CSSProperties, useEffect, useMemo, useRef, useState } from "react";
import { Bell, ChevronDown, Search } from "lucide-react";
import { CommandPalette } from "./CommandPalette";

type UserMenuAction = "profile" | "settings" | "theme" | "logout";

type TopbarProps = {
  breadcrumb?: string;
  userName?: string;
  hasUnreadNotifications?: boolean;
  onNotificationsClick?: () => void;
  onUserAction?: (action: UserMenuAction) => void;
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

const topbarStyle: CSSProperties = {
  position: "sticky",
  top: 0,
  zIndex: 40,
  height: 56,
  display: "grid",
  gridTemplateColumns: "minmax(160px, 1fr) minmax(320px, 560px) auto",
  alignItems: "center",
  gap: 16,
  padding: "0 16px",
  borderBottom: "1px solid var(--border)",
  background: "var(--surface)",
};

export function Topbar({
  breadcrumb = "Hallinta · Etusivu",
  userName = "Pindora Admin",
  hasUnreadNotifications = true,
  onNotificationsClick,
  onUserAction,
  onNavigate,
  onCreateInvoice,
  onCreateReservation,
  onCreateCustomer,
  searchResults,
}: TopbarProps) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [isMac, setIsMac] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (typeof navigator !== "undefined") {
      const platform = navigator.platform || "";
      setIsMac(platform.toUpperCase().includes("MAC"));
    }
  }, []);

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (!menuRef.current) {
        return;
      }
      if (!menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const initials = useMemo(() => {
    const parts = userName.trim().split(/\s+/).filter(Boolean);
    return (parts[0]?.[0] ?? "P") + (parts[1]?.[0] ?? "A");
  }, [userName]);

  return (
    <>
      <header style={topbarStyle}>
        <div style={{ fontSize: 13, color: "var(--text-muted)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {breadcrumb}
        </div>

        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          aria-label="Avaa haku"
          style={{
            height: 38,
            border: "1px solid var(--border)",
            borderRadius: 10,
            background: "var(--surface)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            padding: "0 12px",
            color: "var(--text-soft)",
            cursor: "pointer",
          }}
        >
          <span style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
            <Search size={14} color="var(--text-soft)" />
            <span style={{ fontSize: 13, color: "var(--text-soft)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              Hae varauksia, asiakkaita, laskuja...
            </span>
          </span>
          <kbd
            style={{
              border: "1px solid var(--border)",
              background: "var(--bg)",
              borderRadius: 8,
              padding: "2px 7px",
              fontSize: 11,
              color: "var(--text-muted)",
              lineHeight: "14px",
            }}
          >
            {isMac ? "⌘K" : "Ctrl K"}
          </kbd>
        </button>

        <div style={{ justifySelf: "end", display: "flex", alignItems: "center", gap: 12 }}>
          <button
            type="button"
            onClick={onNotificationsClick}
            aria-label="Notifications"
            style={iconButtonStyle}
          >
            <Bell size={16} />
            {hasUnreadNotifications && (
              <span
                aria-hidden
                style={{
                  position: "absolute",
                  top: 8,
                  right: 8,
                  width: 8,
                  height: 8,
                  borderRadius: "50%",
                  background: "#EF4444",
                }}
              />
            )}
          </button>

          <div ref={menuRef} style={{ position: "relative" }}>
            <button
              type="button"
              onClick={() => setMenuOpen((value) => !value)}
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              style={{
                border: "1px solid var(--border)",
                background: "var(--surface)",
                borderRadius: 999,
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "4px 8px 4px 4px",
                cursor: "pointer",
              }}
            >
              <span
                aria-hidden
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "50%",
                  display: "grid",
                  placeItems: "center",
                  background: "linear-gradient(135deg, #DC2626, #7C3AED)",
                  color: "#ffffff",
                  fontSize: 12,
                  fontWeight: 600,
                  letterSpacing: "0.03em",
                }}
              >
                {initials.toUpperCase()}
              </span>
              <ChevronDown size={14} color="var(--text-soft)" />
            </button>

            {menuOpen && (
              <div
                role="menu"
                style={{
                  position: "absolute",
                  right: 0,
                  top: "calc(100% + 10px)",
                  minWidth: 180,
                  borderRadius: 10,
                  border: "1px solid var(--border)",
                  background: "var(--surface)",
                  boxShadow: "var(--shadow-md)",
                  padding: 6,
                }}
              >
                {[
                  { key: "profile", label: "Profile" },
                  { key: "settings", label: "Settings" },
                  { key: "theme", label: "Theme" },
                  { key: "logout", label: "Logout" },
                ].map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      onUserAction?.(item.key as UserMenuAction);
                      setMenuOpen(false);
                    }}
                    style={menuButtonStyle}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
      </header>

      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        onNavigate={onNavigate}
        onCreateInvoice={onCreateInvoice}
        onCreateReservation={onCreateReservation}
        onCreateCustomer={onCreateCustomer}
        searchResults={searchResults}
      />
    </>
  );
}

const iconButtonStyle: CSSProperties = {
  position: "relative",
  width: 36,
  height: 36,
  borderRadius: 10,
  border: "1px solid var(--border)",
  background: "var(--surface)",
  display: "grid",
  placeItems: "center",
  color: "var(--text-soft)",
  cursor: "pointer",
};

const menuButtonStyle: CSSProperties = {
  width: "100%",
  border: 0,
  background: "transparent",
  textAlign: "left",
  padding: "9px 10px",
  borderRadius: 8,
  color: "var(--text)",
  fontSize: 13,
  cursor: "pointer",
};
