import * as React from "react";
import { Text } from "@react-email/components";
import { Button } from "./components/Button";
import { Layout } from "./components/Layout";

type ContractSignEmailProps = {
  customerName?: string;
  contractName?: string;
  signUrl?: string;
};

export default function ContractSignEmail({
  customerName = "Asiakas",
  contractName = "Vuokrasopimus 2026",
  signUrl = "https://example.com/contracts/123/sign",
}: ContractSignEmailProps) {
  return (
    <Layout preview={`Allekirjoita sopimus: ${contractName}`}>
      <Text style={styles.h1}>Allekirjoituspyyntö</Text>
      <Text style={styles.text}>
        Hei {customerName}, sopimus <strong>{contractName}</strong> odottaa allekirjoitustasi.
      </Text>
      <Text style={styles.text}>Avaa alla oleva linkki ja allekirjoita sopimus turvallisesti verkossa.</Text>
      <Button href={signUrl}>Allekirjoita sopimus</Button>
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
