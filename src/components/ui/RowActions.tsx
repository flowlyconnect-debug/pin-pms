import { type CSSProperties, useEffect, useRef, useState } from "react";

type RowActionItem = {
  id: "view" | "edit" | "resend" | "copy-ref" | "delete";
  label: string;
  danger?: boolean;
  onClick?: () => void;
};

type RowActionsProps = {
  actions?: RowActionItem[];
};

const defaultActions: RowActionItem[] = [
  { id: "view", label: "Nayta" },
  { id: "edit", label: "Muokkaa" },
  { id: "resend", label: "Laheta uudelleen" },
  { id: "copy-ref", label: "Kopioi viite" },
  { id: "delete", label: "Poista", danger: true },
];

export function RowActions({ actions = defaultActions }: RowActionsProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, []);

  return (
    <div ref={ref} style={{ position: "relative", display: "inline-block" }}>
      <button
        type="button"
        aria-label="Rivitoiminnot"
        onClick={() => setOpen((value) => !value)}
        style={triggerStyle}
      >
        ⋯
      </button>
      {open && (
        <div role="menu" style={menuStyle}>
          {actions.map((item) => (
            <button
              key={item.id}
              type="button"
              role="menuitem"
              onClick={() => {
                item.onClick?.();
                setOpen(false);
              }}
              style={{
                ...itemStyle,
                color: item.danger ? "var(--color-danger)" : "var(--color-text)",
              }}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

const triggerStyle: CSSProperties = {
  border: 0,
  background: "transparent",
  color: "var(--text-muted, var(--color-text-muted))",
  cursor: "pointer",
  fontSize: 18,
  lineHeight: 1,
  padding: "2px 4px",
};

const menuStyle: CSSProperties = {
  position: "absolute",
  right: 0,
  top: "calc(100% + 6px)",
  minWidth: 170,
  border: "1px solid var(--color-border)",
  borderRadius: 10,
  background: "var(--color-surface)",
  boxShadow: "var(--shadow-md)",
  padding: 6,
  zIndex: 20,
};

const itemStyle: CSSProperties = {
  display: "block",
  width: "100%",
  border: 0,
  background: "transparent",
  textAlign: "left",
  padding: "8px 10px",
  borderRadius: 8,
  cursor: "pointer",
  fontSize: 13,
};
