import { useId, useState, type InputHTMLAttributes } from "react";

type RadioProps = Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label: string;
};

export function Radio({ id, label, checked, ...props }: RadioProps) {
  const fallbackId = useId();
  const inputId = id ?? fallbackId;
  const [isFocused, setIsFocused] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  return (
    <label htmlFor={inputId} style={rowStyle}>
      <span
        style={{
          ...controlStyle,
          ...(isHovered ? hoverStyle : null),
          ...(isFocused ? focusStyle : null),
          ...(checked ? checkedStyle : null),
        }}
      >
        <input
          {...props}
          id={inputId}
          type="radio"
          checked={checked}
          style={inputStyle}
          onFocus={(event) => {
            setIsFocused(true);
            props.onFocus?.(event);
          }}
          onBlur={(event) => {
            setIsFocused(false);
            props.onBlur?.(event);
          }}
          onMouseEnter={(event) => {
            setIsHovered(true);
            props.onMouseEnter?.(event);
          }}
          onMouseLeave={(event) => {
            setIsHovered(false);
            props.onMouseLeave?.(event);
          }}
        />
        {checked ? <span aria-hidden style={dotStyle} /> : null}
      </span>
      <span>{label}</span>
    </label>
  );
}

const rowStyle = {
  display: "inline-flex",
  alignItems: "center",
  gap: 8,
  cursor: "pointer",
  color: "var(--color-text)",
  fontSize: 14,
} as const;

const controlStyle = {
  width: 18,
  height: 18,
  flexShrink: 0,
  border: "1.5px solid var(--color-border-strong)",
  borderRadius: "50%",
  background: "var(--color-surface)",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  position: "relative" as const,
  transition: "border-color 120ms ease, background-color 120ms ease, box-shadow 120ms ease",
} as const;

const dotStyle = {
  width: 8,
  height: 8,
  borderRadius: "50%",
  background: "#fff",
};

const hoverStyle = {
  borderColor: "var(--text-soft, var(--color-text-muted))",
};

const focusStyle = {
  boxShadow: "0 0 0 3px var(--color-primary-soft)",
};

const checkedStyle = {
  background: "var(--color-primary)",
  borderColor: "var(--color-primary)",
};

const inputStyle = {
  position: "absolute" as const,
  inset: 0,
  margin: 0,
  opacity: 0,
  cursor: "pointer",
};
