import type { ReactNode } from "react";

import "./globals.css";

export const metadata = {
  title: "Relay",
  description: "Payment timelines, explanations and failover (synthetic data)",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
