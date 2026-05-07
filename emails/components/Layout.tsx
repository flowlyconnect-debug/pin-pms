import * as React from "react";
import { Body, Container, Head, Hr, Html, Img, Link, Preview, Section, Text } from "@react-email/components";

type LayoutProps = {
  preview: string;
  children: React.ReactNode;
};

const logoPng =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAQAAABi6S9dAAAAPUlEQVR42mP8z8Dwn4GKgImahoYGFjAxMTHxD4M0mAEjMwMDA4P/B4P9T2A0YGBgqM6B0VqQGQ3Q0NDQwMAABY0D5Nf4Vw0AAAAASUVORK5CYII=";

export function Layout({ preview, children }: LayoutProps) {
  return (
    <Html>
      <Head />
      <Preview>{preview}</Preview>
      <Body style={styles.body}>
        <Container style={styles.container}>
          <Section style={styles.header}>
            <Img alt="Pin PMS logo" src={logoPng} width="32" height="32" style={styles.logo} />
            <Text style={styles.wordmark}>Pin PMS</Text>
          </Section>

          <Section style={styles.card}>{children}</Section>

          <Hr style={styles.divider} />
          <Text style={styles.footer}>
            Pin PMS · Flowly Solutions · Katuosoite 1, 00100 Helsinki ·{" "}
            <Link href="https://example.com/unsubscribe" style={styles.footerLink}>
              Peruuta tilaus
            </Link>
          </Text>
        </Container>
      </Body>
    </Html>
  );
}

const styles = {
  body: {
    margin: 0,
    padding: "24px 12px",
    backgroundColor: "#FAFAF9",
    fontFamily: '-apple-system, "Segoe UI", sans-serif',
    color: "#0C0A09",
  },
  container: {
    maxWidth: "600px",
    margin: "0 auto",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    marginBottom: "16px",
  },
  logo: {
    borderRadius: "8px",
  },
  wordmark: {
    margin: 0,
    fontSize: "20px",
    fontWeight: "700",
    lineHeight: "32px",
    color: "#0C0A09",
  },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: "12px",
    padding: "32px",
  },
  divider: {
    borderColor: "#E7E5E4",
    margin: "18px 0 10px",
  },
  footer: {
    margin: 0,
    fontSize: "12px",
    lineHeight: "18px",
    color: "#57534E",
  },
  footerLink: {
    color: "#57534E",
    textDecoration: "underline",
  },
};
