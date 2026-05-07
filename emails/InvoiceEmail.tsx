import * as React from "react";
import { Link, Section, Text } from "@react-email/components";
import { Button } from "./components/Button";
import { Layout } from "./components/Layout";

type InvoiceEmailProps = {
  customerName?: string;
  invoiceNumber?: string;
  dueDate?: string;
  amount?: string;
  vatBreakdown?: string;
  payUrl?: string;
  pdfUrl?: string;
};

export default function InvoiceEmail({
  customerName = "Asiakas",
  invoiceNumber = "BIL-001",
  dueDate = "31.05.2026",
  amount = "1 250,00 EUR",
  vatBreakdown = "ALV 25,5 %: 254,00 EUR",
  payUrl = "https://example.com/invoices/BIL-001/pay",
  pdfUrl = "https://example.com/invoices/BIL-001.pdf",
}: InvoiceEmailProps) {
  return (
    <Layout preview={`Uusi lasku #${invoiceNumber}`}>
      <Text style={styles.h1}>Uusi lasku #{invoiceNumber}</Text>
      <Text style={styles.text}>Hei {customerName}, olemme luoneet uuden laskun joka erääntyy {dueDate}.</Text>

      <Section style={styles.invoiceCard}>
        <Text style={styles.row}>Numero: {invoiceNumber}</Text>
        <Text style={styles.row}>Eräpäivä: {dueDate}</Text>
        <Text style={styles.amount}>{amount}</Text>
        <Text style={styles.vat}>{vatBreakdown}</Text>
      </Section>

      <Section style={styles.ctaWrap}>
        <Button href={payUrl}>Maksa lasku</Button>
      </Section>
      <Text style={styles.secondary}>
        <Link href={pdfUrl} style={styles.secondaryLink}>
          Lataa PDF
        </Link>
      </Text>
    </Layout>
  );
}

const styles = {
  h1: {
    margin: "0 0 12px",
    fontSize: "28px",
    lineHeight: "34px",
    fontWeight: "700",
    color: "#0C0A09",
  },
  text: {
    margin: "0 0 18px",
    fontSize: "16px",
    lineHeight: "24px",
    color: "#57534E",
  },
  invoiceCard: {
    borderRadius: "10px",
    border: "1px solid #E7E5E4",
    backgroundColor: "#FAFAF9",
    padding: "18px",
  },
  row: {
    margin: "0 0 8px",
    fontSize: "14px",
    lineHeight: "20px",
    color: "#0C0A09",
  },
  amount: {
    margin: "8px 0 6px",
    fontSize: "28px",
    lineHeight: "34px",
    fontWeight: "700",
    color: "#0C0A09",
  },
  vat: {
    margin: 0,
    fontSize: "13px",
    lineHeight: "19px",
    color: "#57534E",
  },
  ctaWrap: {
    marginTop: "20px",
  },
  secondary: {
    margin: "14px 0 0",
    fontSize: "14px",
    lineHeight: "20px",
  },
  secondaryLink: {
    color: "#B91C1C",
    textDecoration: "underline",
  },
};
