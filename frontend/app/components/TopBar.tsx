"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";
import { useAuth } from "../../lib/auth";

export function TopBar() {
  const path = usePathname();
  const { user, logout, has } = useAuth();
  const [chain, setChain] = useState<{ intact: boolean; count: number } | null>(null);

  useEffect(() => {
    if (!user) { setChain(null); return; }
    api.verifyAudit().then(setChain).catch(() => setChain(null));
  }, [path, user]);

  const is = (p: string) => (path === p || path.startsWith(p + "/") ? "active" : "");
  if (path === "/login") return null;

  return (
    <div className="topbar">
      <Link href="/" className="brand">
        <span className="mk">F</span>
        <span>Frontdoor</span>
      </Link>
      {user && (
        <nav className="topnav">
          {has("request:read_all") && <Link href="/inbox" className={is("/inbox")}>Legal inbox</Link>}
          {has("request:create") && <Link href="/new" className={is("/new")}>Request an NDA</Link>}
          {has("request:read_all") && <Link href="/inbound" className={is("/inbound")}>Review their paper</Link>}
          {has("admin:manage_users") && <Link href="/admin" className={is("/admin")}>Admin</Link>}
        </nav>
      )}
      <span className="spacer" />
      {chain && (
        <span className="chip-verify" title={`${chain.count} audit events`}>
          {chain.intact ? "✓ Audit chain intact" : "✕ Audit chain broken"}
        </span>
      )}
      {user && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginLeft: 4 }}>
          <div style={{ textAlign: "right", lineHeight: 1.2 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600 }}>{user.name}</div>
            <div style={{ fontSize: 10.5, color: "var(--muted)", textTransform: "uppercase", letterSpacing: ".04em" }}>{user.role.replace(/_/g, " ")}</div>
          </div>
          <button className="btn ghost" style={{ padding: "6px 10px", fontSize: 12.5 }} onClick={logout}>Sign out</button>
        </div>
      )}
    </div>
  );
}
