import type { CSSProperties, ReactNode } from "react";

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

function buildSparklinePoints(values: number[]): string {
  if (values.length === 0) {
    return "";
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const width = 60;
  const height = 20;
  return values
    .map((v, index) => {
      const x = (index / Math.max(values.length - 1, 1)) * width;
      const y = height - ((v - min) / range) * height;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
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
  const polylinePoints = buildSparklinePoints(sparkline);
  const areaPoints = polylinePoints ? `0,20 ${polylinePoints} 60,20` : "";

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
      <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>{meta}</p>

      {polylinePoints && (
        <svg width="60" height="20" viewBox="0 0 60 20" role="img" aria-label={`${label} sparkline`}>
          <polygon points={areaPoints} fill="var(--color-primary, #c62828)" opacity="0.2" />
          <polyline
            points={polylinePoints}
            fill="none"
            stroke="var(--color-primary, #c62828)"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </article>
  );
}
