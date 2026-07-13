"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "../../lib/api";

export function TopBar() {
  const path = usePathname();
  const [chain, setChain] = useState<{ intact: boolean; count: number } | null>(null);

  useEffect(() => {
    api.verifyAudit().then((r) => setChain(r)).catch(() => setChain(null));
  }, [path]);

  const is = (p: string) => (path === p || path.startsWith(p + "/") ? "active" : "");

  return (
    <div className="topbar">
      <Link href="/" className="brand">
        <span className="mk">F</span>
        <span>Frontdoor</span>
      </Link>
      <nav className="topnav">
        <Link href="/inbox" className={is("/inbox")}>Legal inbox</Link>
        <Link href="/new" className={is("/new")}>Request an NDA</Link>
        <Link href="/inbound" className={is("/inbound")}>Review their paper</Link>
      </nav>
      <span className="spacer" />
      {chain && (
        <span className="chip-verify" title={`${chain.count} audit events`}>
          {chain.intact ? "✓ Audit chain intact" : "✕ Audit chain broken"}
        </span>
      )}
    </div>
  );
}
