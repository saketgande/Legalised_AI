"use client";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { isPublicShell, useAuth } from "../../lib/auth";
import { CommandPalette } from "./CommandPalette";
import { Sidebar } from "./Sidebar";
import { IconMoon, IconSun } from "./Icons";

const TITLES: [RegExp, string][] = [
  [/^\/$/, "Dashboard"],
  [/^\/inbox/, "Legal inbox"],
  [/^\/contracts/, "Contract registry"],
  [/^\/sla/, "SLA & operations"],
  [/^\/new/, "New request"],
  [/^\/chat/, "Ask legal"],
  [/^\/inbound/, "Review their paper"],
  [/^\/email-sim/, "Email intake"],
  [/^\/review\//, "Redline cockpit"],
  [/^\/r\//, "Request status"],
  [/^\/admin\/playbook/, "Playbook"],
  [/^\/admin\/routing/, "Routing rules"],
  [/^\/admin/, "Users & roles"],
];
function titleFor(path: string): string {
  return TITLES.find(([re]) => re.test(path))?.[1] ?? "Frontdoor";
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);
  useEffect(() => {
    const saved = (typeof localStorage !== "undefined" && localStorage.getItem("fd-theme")) as
      | "light" | "dark" | null;
    const initial =
      saved ??
      (window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    setTheme(initial);
    document.documentElement.setAttribute("data-theme", initial);
  }, []);
  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("fd-theme", next); } catch {}
  }
  if (!theme) return null;
  return (
    <button className="icon-btn" onClick={toggle} title="Toggle theme" aria-label="Toggle theme">
      {theme === "dark" ? <IconSun /> : <IconMoon />}
    </button>
  );
}

function TopBar() {
  const path = usePathname();
  const { user } = useAuth();
  const [chain, setChain] = useState<{ intact: boolean; count: number } | null>(null);
  useEffect(() => {
    if (!user) { setChain(null); return; }
    api.verifyAudit().then(setChain).catch(() => setChain(null));
  }, [path, user]);
  return (
    <header className="topbar">
      <span className="tb-title">{titleFor(path)}</span>
      <span className="spacer" />
      {chain && (
        <span className="chip-verify" title={`${chain.count} audit events`}>
          {chain.intact ? "✓ Audit chain intact" : "✕ Audit chain broken"}
        </span>
      )}
      <ThemeToggle />
    </header>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { user } = useAuth();

  // Public shells (login, Word add-in) render standalone — no sidebar chrome.
  if (isPublicShell(path)) return <>{children}</>;
  // Not signed in yet: AuthGate handles the redirect/loading UI; render bare.
  if (!user) return <>{children}</>;

  return (
    <div className="shell">
      <Sidebar />
      <div className="shell-main">
        <TopBar />
        <main className="shell-content">{children}</main>
      </div>
      <CommandPalette />
    </div>
  );
}
