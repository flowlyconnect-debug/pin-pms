import * as React from "react";
import { Text } from "@react-email/components";
import { Button } from "./components/Button";
import { Layout } from "./components/Layout";

type InvoiceOverdueEmailProps = {
  customerName?: string;
  invoiceNumber?: string;
  amount?: string;
  overdueDays?: number;
  payUrl?: string;
};

export default function InvoiceOverdueEmail({
  customerName = "Asiakas",
  invoiceNumber = "BIL-001",
  amount = "1 250,00 EUR",
  overdueDays = 7,
  payUrl = "https://example.com/invoices/BIL-001/pay",
}: InvoiceOverdueEmailProps) {
  return (
    <Layout preview={`Lasku #${invoiceNumber} on myöhässä`}>
      <Text style={styles.h1}>Lasku #{invoiceNumber} on myöhässä</Text>
      <Text style={styles.text}>
        Hei {customerName}, lasku {invoiceNumber} ({amount}) on ollut avoinna {overdueDays} päivää eräpäivän jälkeen.
      </Text>
      <Text style={styles.warning}>Pyydämme suorittamaan maksun mahdollisimman pian, jotta palvelu ei keskeydy.</Text>
      <Button href={payUrl}>Maksa myöhästynyt lasku</Button>
    </Layout>
  );
}

const styles = {
  h1: {
    margin: "0 0 12px",
    fontSize: "26px",
    lineHeight: "32px",
    fontWeight: "700",
    color: "#B91C1C",
  },
  text: {
    margin: "0 0 12px",
    fontSize: "16px",
    lineHeight: "24px",
    color: "#57534E",
  },
  warning: {
    margin: "0 0 20px",
    fontSize: "14px",
    lineHeight: "20px",
    color: "#0C0A09",
  },
};
