import * as React from "react";
import { Button as EmailButton } from "@react-email/components";

type ButtonProps = {
  href: string;
  children: React.ReactNode;
};

export function Button({ href, children }: ButtonProps) {
  return (
    <EmailButton href={href} style={styles.button}>
      {children}
    </EmailButton>
  );
}

const styles = {
  button: {
    display: "inline-block",
    borderRadius: "10px",
    backgroundColor: "#B91C1C",
    color: "#FFFFFF",
    fontSize: "14px",
    fontWeight: "600",
    textDecoration: "none",
    padding: "12px 20px",
  },
};
