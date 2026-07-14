"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "../../lib/auth";
import { IconSignOut } from "./Icons";

// Aurora palette glyphs + colours, mirroring legal_intake/apps/web/src/data/nav.js
const C = { em: "#E8793B", bl: "#6B8EC4", tl: "#6BA4A4", am: "#E0B34A", rd: "#C8463D", pp: "#A06C9A", cy: "#6BA4A4" };
type Item = { href: string; label: string; perm: string | null; gl: string; c: string };
type Group = { label: string; items: Item[] };

const GROUPS: Group[] = [
  {
    label: "Workspace",
    items: [
      { href: "/", label: "Mission Control", perm: null, gl: "◎", c: C.em },
      { href: "/inbox", label: "Legal Intake", perm: "request:read_all", gl: "◆", c: C.cy },
      { href: "/cockpit", label: "Triage Cockpit", perm: "request:read_all", gl: "◈", c: C.em },
      { href: "/workspace", label: "Ops Workspace", perm: "request:read_all", gl: "▦", c: C.pp },
      { href: "/contracts", label: "Contracts", perm: "request:read_all", gl: "▤", c: C.bl },
      { href: "/sla", label: "SLA & Operations", perm: "request:read_all", gl: "◉", c: C.am },
    ],
  },
  {
    label: "Intake",
    items: [
      { href: "/new", label: "New Request", perm: "request:create", gl: "＋", c: C.em },
      { href: "/chat", label: "Ask Legal", perm: "request:create", gl: "◈", c: C.tl },
      { href: "/inbound", label: "Review Their Paper", perm: "request:read_all", gl: "▧", c: C.bl },
      { href: "/email-sim", label: "Email Intake", perm: "request:read_all", gl: "▩", c: C.tl },
    ],
  },
  {
    label: "Platform",
    items: [
      { href: "/admin/playbook", label: "Playbook", perm: "playbook:manage", gl: "▦", c: C.am },
      { href: "/admin/workflows", label: "Workflows", perm: "intake:manage", gl: "▷", c: C.tl },
      { href: "/admin/routing", label: "Routing Rules", perm: "intake:manage", gl: "▶", c: C.pp },
      { href: "/admin", label: "Users & Roles", perm: "admin:manage_users", gl: "◈", c: C.bl },
    ],
  },
];

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function Sidebar() {
  const path = usePathname();
  const { user, logout, has } = useAuth();
  const active = (href: string) =>
    href === "/" ? path === "/" : path === href || path.startsWith(href + "/");

  return (
    <aside className="sidebar">
      <Link href="/" className="sb-brand">
        <span className="mk">F</span>
        <span className="nm">Frontdoor<small>LEGAL MISSION CONTROL</small></span>
      </Link>

      <nav className="sb-nav">
        {GROUPS.map((g) => {
          const items = g.items.filter((it) => it.perm === null || has(it.perm));
          if (!items.length) return null;
          return (
            <div key={g.label}>
              <div className="sb-group-label">{g.label}</div>
              {items.map(({ href, label, gl, c }) => {
                const on = active(href);
                return (
                  <Link key={href} href={href} className={`sb-link ${on ? "active" : ""}`}>
                    <span className="gl" style={{ color: on ? "var(--accent)" : c }}>{gl}</span>
                    <span>{label}</span>
                  </Link>
                );
              })}
            </div>
          );
        })}
      </nav>

      {user && (
        <div className="sb-foot">
          <span className="avatar">{initials(user.name)}</span>
          <span className="who">
            <div className="n">{user.name}</div>
            <div className="r">{user.role.replace(/_/g, " ")}</div>
          </span>
          <button className="icon-btn" title="Sign out" onClick={logout} aria-label="Sign out">
            <IconSignOut />
          </button>
        </div>
      )}
    </aside>
  );
}
