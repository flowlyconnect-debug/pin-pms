import type { CSSProperties, ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

type EmptyStateProps = {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
};

const rootStyle: CSSProperties = {
  minHeight: 280,
  width: "100%",
  display: "grid",
  placeItems: "center",
  textAlign: "center",
  padding: "24px 16px",
};

const contentStyle: CSSProperties = {
  maxWidth: 480,
  display: "grid",
  justifyItems: "center",
  gap: 10,
};

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <section style={rootStyle} aria-live="polite">
      <div style={contentStyle}>
        <Icon size={64} color="var(--text-soft)" strokeWidth={1.6} aria-hidden />
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 600, color: "var(--text)" }}>{title}</h2>
        <p style={{ margin: 0, fontSize: 14, color: "var(--text-muted)" }}>{description}</p>
        {action ? <div style={{ marginTop: 8 }}>{action}</div> : null}
      </div>
    </section>
  );
}
