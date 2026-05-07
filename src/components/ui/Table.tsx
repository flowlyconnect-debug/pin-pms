import type { CSSProperties, ReactNode } from "react";

type TableProps = {
  headers: ReactNode[];
  children: ReactNode;
  clickableRows?: boolean;
};

type EmptyStateProps = {
  title: string;
  description?: string;
  image?: ReactNode;
  ctaLabel: string;
  onPrimaryAction?: () => void;
};

export function Table({ headers, children, clickableRows = false }: TableProps) {
  return (
    <div style={shellStyle}>
      <table style={tableStyle}>
        <thead>
          <tr>
            {headers.map((header, index) => (
              <th key={index} style={headerStyle}>
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody style={clickableRows ? clickableBodyStyle : undefined}>{children}</tbody>
      </table>
    </div>
  );
}

export function TableCell({ children }: { children: ReactNode }) {
  return <td style={cellStyle}>{children}</td>;
}

export function EmptyState({ title, description, image, ctaLabel, onPrimaryAction }: EmptyStateProps) {
  return (
    <div style={emptyStateStyle}>
      {image ? <div>{image}</div> : null}
      <strong style={{ fontSize: 16 }}>{title}</strong>
      {description ? <p style={{ margin: 0, color: "var(--text-muted, var(--color-text-muted))" }}>{description}</p> : null}
      <button type="button" onClick={onPrimaryAction} style={ctaStyle}>
        {ctaLabel}
      </button>
    </div>
  );
}

const shellStyle: CSSProperties = {
  border: "1px solid var(--border, var(--color-border))",
  borderRadius: 14,
  overflow: "hidden",
  background: "var(--surface, var(--color-surface))",
};

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "separate",
  borderSpacing: 0,
};

const headerStyle: CSSProperties = {
  padding: "12px 16px",
  fontSize: 11,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  fontWeight: 600,
  color: "var(--text-soft, var(--color-text-muted))",
  background: "var(--bg-alt, var(--color-surface-2))",
  borderBottom: "1px solid var(--border, var(--color-border))",
  textAlign: "left",
};

const cellStyle: CSSProperties = {
  padding: "14px 16px",
  fontSize: 14,
  borderBottom: "1px solid var(--border, var(--color-border))",
};

const clickableBodyStyle: CSSProperties = {
  cursor: "pointer",
};

const emptyStateStyle: CSSProperties = {
  padding: "28px 16px",
  textAlign: "center",
  display: "grid",
  gap: 8,
  justifyItems: "center",
};

const ctaStyle: CSSProperties = {
  border: 0,
  borderRadius: 10,
  background: "var(--color-primary)",
  color: "#fff",
  fontWeight: 600,
  padding: "10px 14px",
  cursor: "pointer",
};
