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
  [/^\/admin\/workflows/, "Workflows & governance"],
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
    const initial = saved ?? "dark";   // AEGIS Aurora (dark) is the default look
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

function LiveClock() {
  const [now, setNow] = useState<string>("");
  useEffect(() => {
    const tick = () => setNow(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, []);
  const date = new Date().toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" });
  return <span className="tb-clock">{now} · {date}</span>;
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
      <span>
        <span className="tb-eyebrow">Operations</span>
        <div className="tb-title">{titleFor(path)}</div>
      </span>
      <span className="spacer" />
      <span className="tb-live"><span className="d" /> Live</span>
      <LiveClock />
      {chain && (
        <span className="chip-verify" title={`${chain.count} audit events`}>
          {chain.intact ? "✓ Chain intact" : "✕ Chain broken"}
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
