import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "CargoAI | Freight Request Extraction",
  description: "Experimental alpha for freight request extraction.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
