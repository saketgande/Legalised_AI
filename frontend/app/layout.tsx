import type { Metadata } from "next";
import "./globals.css";
import { TopBar } from "./components/TopBar";
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
          <TopBar />
          <AuthGate>{children}</AuthGate>
        </AuthProvider>
      </body>
    </html>
  );
}
