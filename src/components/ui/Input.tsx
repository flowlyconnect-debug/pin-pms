import { useState, type CSSProperties, type InputHTMLAttributes } from "react";

type InputProps = InputHTMLAttributes<HTMLInputElement>;

export function Input(props: InputProps) {
  const [isFocused, setIsFocused] = useState(false);

  return (
    <input
      {...props}
      style={{ ...inputStyle, ...(isFocused ? focusStyle : null), ...props.style }}
      onFocus={(event) => {
        setIsFocused(true);
        props.onFocus?.(event);
      }}
      onBlur={(event) => {
        setIsFocused(false);
        props.onBlur?.(event);
      }}
    />
  );
}

const inputStyle: CSSProperties = {
  width: "100%",
  padding: "8px 12px",
  border: "1px solid var(--color-border-strong)",
  borderRadius: 6,
  fontSize: 14,
  lineHeight: 1.4,
  background: "var(--color-surface)",
  color: "var(--color-text)",
  outline: "none",
  transition: "border-color 120ms ease, box-shadow 120ms ease",
};

const focusStyle: CSSProperties = {
  borderColor: "var(--color-primary)",
  boxShadow: "0 0 0 3px var(--color-primary-soft)",
};
