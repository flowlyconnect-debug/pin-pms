import type { CSSProperties, ReactNode } from "react";
import { Sparkline } from "./Sparkline";

type StatCardIntent = "default" | "success" | "warning" | "danger";

type StatCardProps = {
  label: string;
  value: string | number;
  trend: number;
  meta: string;
  icon: ReactNode;
  sparkline?: number[];
  intent?: StatCardIntent;
};

const intentBg: Record<StatCardIntent, string> = {
  default: "var(--color-surface-2, #f4f1ec)",
  success: "var(--color-success-soft, #f0fdf4)",
  warning: "var(--color-warning-soft, #fffbeb)",
  danger: "var(--color-danger-soft, #fef2f2)",
};

const intentSparklineStroke: Record<StatCardIntent, string> = {
  default: "var(--primary)",
  success: "#15803D",
  warning: "#B45309",
  danger: "#DC2626",
};

const intentSparklineFill: Record<StatCardIntent, string> = {
  default: "var(--primary-soft)",
  success: "rgba(21, 128, 61, 0.2)",
  warning: "rgba(180, 83, 9, 0.2)",
  danger: "rgba(220, 38, 38, 0.2)",
};

const rootStyle: CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 10,
  padding: 20,
  background: "var(--surface)",
  transition: "border-color 120ms ease, box-shadow 120ms ease",
  display: "grid",
  gap: 8,
};

function formatByLabel(value: string | number, label: string): string {
  if (typeof value === "string") {
    return value;
  }

  const normalized = label.toLowerCase();
  if (normalized.includes("käyttöaste") || normalized.includes("%")) {
    return `${value.toLocaleString("fi-FI", {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    })} %`;
  }

  if (
    normalized.includes("tulot") ||
    normalized.includes("kulut") ||
    normalized.includes("kassavirta") ||
    normalized.includes("euro")
  ) {
    return new Intl.NumberFormat("fi-FI", {
      style: "currency",
      currency: "EUR",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  }

  return value.toLocaleString("fi-FI");
}

export function StatCard({
  label,
  value,
  trend,
  meta,
  icon,
  sparkline = [],
  intent = "default",
}: StatCardProps) {
  const formattedValue = formatByLabel(value, label);
  const trendUp = trend >= 0;
  const trendColor = trendUp ? "var(--color-success, #16a34a)" : "var(--color-danger, #dc2626)";
  const trendArrow = trendUp ? "↗" : "↘";
  const trendPrefix = trend > 0 ? "+" : "";
  const trendText = `${trendArrow} ${trendPrefix}${trend.toLocaleString("fi-FI", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  })}% vs. ed. kk`;
  return (
    <article style={rootStyle}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
        <p
          style={{
            margin: 0,
            fontSize: 11,
            fontWeight: 600,
            letterSpacing: "0.08em",
            textTransform: "uppercase",
            color: "var(--text-soft)",
          }}
        >
          {label}
        </p>
        <span
          aria-hidden
          style={{
            width: 28,
            height: 28,
            borderRadius: 999,
            display: "grid",
            placeItems: "center",
            background: intentBg[intent],
          }}
        >
          {icon}
        </span>
      </div>

      <p style={{ margin: 0, fontSize: 28, fontWeight: 700, letterSpacing: "-0.02em" }}>{formattedValue}</p>
      <p style={{ margin: 0, fontSize: 12, color: trendColor }}>{trendText}</p>
      <Sparkline
        data={sparkline}
        stroke={intentSparklineStroke[intent]}
        fill={intentSparklineFill[intent]}
      />
      <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>{meta}</p>
    </article>
  );
}
