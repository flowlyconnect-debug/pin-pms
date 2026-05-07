import * as React from "react";
import { Text } from "@react-email/components";
import { Button } from "./components/Button";
import { Layout } from "./components/Layout";

type InvoiceReminderEmailProps = {
  customerName?: string;
  invoiceNumber?: string;
  dueDate?: string;
  amount?: string;
  payUrl?: string;
};

export default function InvoiceReminderEmail({
  customerName = "Asiakas",
  invoiceNumber = "BIL-001",
  dueDate = "31.05.2026",
  amount = "1 250,00 EUR",
  payUrl = "https://example.com/invoices/BIL-001/pay",
}: InvoiceReminderEmailProps) {
  return (
    <Layout preview={`Muistutus laskusta #${invoiceNumber}`}>
      <Text style={styles.h1}>Muistutus laskusta #{invoiceNumber}</Text>
      <Text style={styles.text}>
        Hei {customerName}, tämä on ystävällinen muistutus laskusta {invoiceNumber}. Laskun summa {amount} erääntyy
        {` ${dueDate}.`}
      </Text>
      <Text style={styles.note}>Jos olet jo maksanut laskun, voit jättää tämän viestin huomiotta.</Text>
      <Button href={payUrl}>Maksa lasku</Button>
    </Layout>
  );
}

const styles = {
  h1: {
    margin: "0 0 12px",
    fontSize: "26px",
    lineHeight: "32px",
    fontWeight: "700",
    color: "#0C0A09",
  },
  text: {
    margin: "0 0 12px",
    fontSize: "16px",
    lineHeight: "24px",
    color: "#57534E",
  },
  note: {
    margin: "0 0 20px",
    fontSize: "14px",
    lineHeight: "20px",
    color: "#57534E",
  },
};
