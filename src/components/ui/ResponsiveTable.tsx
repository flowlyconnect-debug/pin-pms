import { type CSSProperties, type ReactNode, useEffect, useState } from "react";
import { RowActions } from "./RowActions";

type ResponsiveTableColumn<T> = {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
};

type ResponsiveTableProps<T> = {
  rows: T[];
  columns: ResponsiveTableColumn<T>[];
  getRowKey: (row: T, index: number) => string;
  mobilePrimary: (row: T) => ReactNode;
  mobileStatus: (row: T) => ReactNode;
  mobileMeta: (row: T) => ReactNode[];
  mobileActions?: (row: T) => ReactNode;
  emptyState?: ReactNode;
};

function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const media = window.matchMedia(query);
    const onChange = () => setMatches(media.matches);
    onChange();
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, [query]);

  return matches;
}

export function ResponsiveTable<T>({
  rows,
  columns,
  getRowKey,
  mobilePrimary,
  mobileStatus,
  mobileMeta,
  mobileActions,
  emptyState,
}: ResponsiveTableProps<T>) {
  const isMobile = useMediaQuery("(max-width: 767px)");

  if (!rows.length) {
    return <div style={emptyStyle}>{emptyState ?? "Ei rivejä."}</div>;
  }

  if (!isMobile) {
    return (
      <div style={tableShellStyle}>
        <table style={tableStyle}>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} style={headerStyle}>
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => (
              <tr key={getRowKey(row, rowIndex)}>
                {columns.map((column) => (
                  <td key={column.key} style={cellStyle}>
                    {column.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div style={cardListStyle}>
      {rows.map((row, rowIndex) => (
        <article key={getRowKey(row, rowIndex)} style={cardStyle}>
          <div style={cardHeadStyle}>
            <div style={primaryStyle}>{mobilePrimary(row)}</div>
            <div style={statusWrapStyle}>{mobileStatus(row)}</div>
          </div>
          <div style={metaListStyle}>
            {mobileMeta(row).slice(0, 3).map((item, index) => (
              <div key={index} style={metaItemStyle}>
                {item}
              </div>
            ))}
          </div>
          <div style={actionsStyle}>{mobileActions?.(row) ?? <RowActions />}</div>
        </article>
      ))}
    </div>
  );
}

const tableShellStyle: CSSProperties = {
  border: "1px solid var(--color-border)",
  borderRadius: 16,
  overflow: "hidden",
  background: "var(--color-surface)",
};

const tableStyle: CSSProperties = {
  width: "100%",
  borderCollapse: "separate",
  borderSpacing: 0,
};

const headerStyle: CSSProperties = {
  padding: "12px 16px",
  textTransform: "uppercase",
  fontSize: 11,
  letterSpacing: "0.08em",
  color: "var(--color-text-muted)",
  background: "var(--color-surface-2)",
  textAlign: "left",
};

const cellStyle: CSSProperties = {
  padding: "12px 16px",
  borderTop: "1px solid var(--color-border)",
  verticalAlign: "top",
};

const cardListStyle: CSSProperties = {
  display: "grid",
  gap: 10,
};

const cardStyle: CSSProperties = {
  border: "1px solid var(--color-border)",
  borderRadius: 12,
  background: "var(--color-surface)",
  padding: 12,
};

const cardHeadStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "start",
  gap: 8,
};

const primaryStyle: CSSProperties = {
  fontSize: 22,
  fontWeight: 700,
  letterSpacing: "-0.01em",
};

const statusWrapStyle: CSSProperties = {
  flexShrink: 0,
};

const metaListStyle: CSSProperties = {
  marginTop: 8,
  display: "grid",
  gap: 4,
};

const metaItemStyle: CSSProperties = {
  fontSize: 13,
  color: "var(--color-text-muted)",
};

const actionsStyle: CSSProperties = {
  marginTop: 8,
  display: "flex",
  justifyContent: "flex-end",
};

const emptyStyle: CSSProperties = {
  border: "1px dashed var(--color-border)",
  borderRadius: 12,
  padding: 16,
  color: "var(--color-text-muted)",
};
