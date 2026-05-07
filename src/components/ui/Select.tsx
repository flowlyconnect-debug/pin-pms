import { useState, type CSSProperties, type SelectHTMLAttributes } from "react";
import { ChevronDown } from "lucide-react";

type SelectProps = SelectHTMLAttributes<HTMLSelectElement>;

export function Select(props: SelectProps) {
  const [isFocused, setIsFocused] = useState(false);

  return (
    <span style={wrapperStyle}>
      <select
        {...props}
        style={{
          ...selectStyle,
          ...(isFocused ? focusStyle : null),
          ...props.style,
        }}
        onFocus={(event) => {
          setIsFocused(true);
          props.onFocus?.(event);
        }}
        onBlur={(event) => {
          setIsFocused(false);
          props.onBlur?.(event);
        }}
      />
      <ChevronDown size={14} style={iconStyle} aria-hidden />
    </span>
  );
}

const wrapperStyle: CSSProperties = {
  display: "inline-block",
  width: "100%",
  position: "relative",
};

const selectStyle: CSSProperties = {
  width: "100%",
  padding: "8px 30px 8px 12px",
  border: "1px solid var(--color-border-strong)",
  borderRadius: 6,
  fontSize: 14,
  lineHeight: 1.4,
  background: "var(--color-surface)",
  color: "var(--color-text)",
  outline: "none",
  appearance: "none",
  WebkitAppearance: "none",
  transition: "border-color 120ms ease, box-shadow 120ms ease",
};

const focusStyle: CSSProperties = {
  borderColor: "var(--color-primary)",
  boxShadow: "0 0 0 3px var(--color-primary-soft)",
};

const iconStyle: CSSProperties = {
  position: "absolute",
  top: "50%",
  right: 12,
  transform: "translateY(-50%)",
  pointerEvents: "none",
  color: "var(--color-text-muted)",
};
