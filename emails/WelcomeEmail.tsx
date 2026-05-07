import * as React from "react";
import { Text } from "@react-email/components";
import { Button } from "./components/Button";
import { Layout } from "./components/Layout";

type WelcomeEmailProps = {
  customerName?: string;
  dashboardUrl?: string;
};

export default function WelcomeEmail({
  customerName = "Asiakas",
  dashboardUrl = "https://example.com/dashboard",
}: WelcomeEmailProps) {
  return (
    <Layout preview="Tervetuloa Pin PMS:ään">
      <Text style={styles.h1}>Tervetuloa Pin PMS:ään</Text>
      <Text style={styles.text}>
        Hei {customerName}, mahtavaa että liityit mukaan. Pin PMS auttaa sinua hallitsemaan varauksia, laskutusta ja
        sopimuksia yhdessä paikassa.
      </Text>
      <Text style={styles.text}>Aloita kirjautumalla hallintapaneeliin ja viimeistelemällä ensimmäiset asetukset.</Text>
      <Button href={dashboardUrl}>Avaa hallintapaneeli</Button>
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
};
