import type { Metadata } from "next";
import "@fontsource-variable/inter";
import "./globals.css";
import { AppShell } from "./components/AppShell";
import { AuthGate, AuthProvider } from "../lib/auth";

export const metadata: Metadata = {
  title: "Frontdoor — Legal front door + CLM",
  description: "Request-to-signature for NDAs, governed by policy and a tamper-evident audit chain.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <AppShell>
            <AuthGate>{children}</AuthGate>
          </AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
