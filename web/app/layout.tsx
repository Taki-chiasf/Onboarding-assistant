import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Onboarding Assistant",
  description: "Ask questions about company policy, teams, and tools.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
