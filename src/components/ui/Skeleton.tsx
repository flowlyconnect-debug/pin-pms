import type { CSSProperties } from "react";

type SkeletonVariant = "text" | "circle" | "card";

type SkeletonProps = {
  variant?: SkeletonVariant;
  width?: number | string;
  height?: number | string;
};

const baseStyle: CSSProperties = {
  display: "block",
  backgroundImage: "linear-gradient(90deg, var(--bg-alt), var(--border), var(--bg-alt))",
  backgroundSize: "200% 100%",
  animation: "skeletonShimmer 1.5s ease-in-out infinite",
};

export function Skeleton({ variant = "text", width, height }: SkeletonProps) {
  const resolvedStyle: CSSProperties = { ...baseStyle };

  if (variant === "circle") {
    resolvedStyle.width = width ?? 40;
    resolvedStyle.height = height ?? 40;
    resolvedStyle.borderRadius = "50%";
  } else if (variant === "card") {
    resolvedStyle.width = width ?? "100%";
    resolvedStyle.height = height ?? 140;
    resolvedStyle.borderRadius = 12;
    resolvedStyle.border = "1px solid var(--border)";
  } else {
    resolvedStyle.width = width ?? "100%";
    resolvedStyle.height = height ?? 14;
    resolvedStyle.borderRadius = 8;
  }

  return (
    <>
      <style>{`@keyframes skeletonShimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }`}</style>
      <span aria-hidden style={resolvedStyle} />
    </>
  );
}
