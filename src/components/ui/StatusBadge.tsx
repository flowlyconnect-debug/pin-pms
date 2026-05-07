import type { CSSProperties } from "react";

export type StatusVariant = "success" | "warning" | "danger" | "info" | "neutral";

type StatusBadgeProps = {
  label: string;
  status?: string | null;
  variant?: StatusVariant;
};

const statusToVariant: Record<string, StatusVariant> = {
  paid: "success",
  completed: "success",
  active: "success",
  open: "warning",
  pending: "warning",
  overdue: "danger",
  failed: "danger",
  cancelled: "danger",
  draft: "info",
  info: "info",
};

const variantStyles: Record<StatusVariant, { bg: string; text: string; border: string; dot: string }> = {
  success: { bg: "var(--color-success-soft)", text: "var(--color-success)", border: "#bbf7d0", dot: "var(--color-success)" },
  warning: { bg: "var(--color-warning-soft)", text: "var(--color-warning)", border: "#fde68a", dot: "var(--color-warning)" },
  danger: { bg: "var(--color-danger-soft)", text: "var(--color-danger)", border: "#fecaca", dot: "var(--color-danger)" },
  info: { bg: "var(--color-info-soft)", text: "var(--color-info)", border: "#bfdbfe", dot: "var(--color-info)" },
  neutral: { bg: "var(--color-surface-2)", text: "var(--color-text-muted)", border: "var(--color-border)", dot: "var(--color-text-muted)" },
};

export function mapStatusToVariant(status?: string | null): StatusVariant {
  const key = (status || "").trim().toLowerCase();
  return statusToVariant[key] ?? "neutral";
}

export function StatusBadge({ label, status, variant }: StatusBadgeProps) {
  const resolvedVariant = variant ?? mapStatusToVariant(status ?? label);
  const colors = variantStyles[resolvedVariant];

  const rootStyle: CSSProperties = {
    display: "inline-flex",
    alignItems: "center",
    gap: 6,
    padding: "3px 8px",
    borderRadius: 999,
    border: `1px solid ${colors.border}`,
    background: colors.bg,
    color: colors.text,
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    lineHeight: 1.2,
  };

  return (
    <span style={rootStyle}>
      <span
        aria-hidden
        style={{
          width: 6,
          height: 6,
          borderRadius: "50%",
          background: colors.dot,
          flexShrink: 0,
        }}
      />
      {label}
    </span>
  );
}
