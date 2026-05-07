import { AlertTriangle } from "lucide-react";

type ConflictBannerProps = {
  count: number;
  href?: string;
};

export function ConflictBanner({ count, href = "/konfliktit" }: ConflictBannerProps) {
  if (count === 0) {
    return null;
  }

  return (
    <div
      style={{
        background: "#FEF2F2",
        borderLeft: "3px solid var(--primary)",
        padding: "12px 16px",
        borderRadius: "0 6px 6px 0",
        display: "flex",
        alignItems: "center",
        gap: 10,
      }}
    >
      <AlertTriangle size={18} aria-hidden="true" />
      <span style={{ flex: 1 }}>
        Sinulla on {count} konfliktia jotka vaativat huomiota
      </span>
      <a href={href}>Tarkastele →</a>
    </div>
  );
}
