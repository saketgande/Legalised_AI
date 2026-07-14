"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAuth } from "../../lib/auth";
import {
  IconBook, IconChat, IconDashboard, IconGauge, IconInbox, IconMail, IconPlus,
  IconReview, IconShield, IconSignOut, IconUsers,
} from "./Icons";

type Item = { href: string; label: string; perm: string | null; Icon: (p: any) => JSX.Element };
type Group = { label: string; items: Item[] };

const GROUPS: Group[] = [
  {
    label: "Workspace",
    items: [
      { href: "/", label: "Dashboard", perm: null, Icon: IconDashboard },
      { href: "/inbox", label: "Legal inbox", perm: "request:read_all", Icon: IconInbox },
      { href: "/sla", label: "SLA & metrics", perm: "request:read_all", Icon: IconGauge },
    ],
  },
  {
    label: "Intake",
    items: [
      { href: "/new", label: "Request an NDA", perm: "request:create", Icon: IconPlus },
      { href: "/chat", label: "Ask legal", perm: "request:create", Icon: IconChat },
      { href: "/inbound", label: "Review their paper", perm: "request:read_all", Icon: IconReview },
      { href: "/email-sim", label: "Email intake", perm: "request:read_all", Icon: IconMail },
    ],
  },
  {
    label: "Administration",
    items: [
      { href: "/admin/playbook", label: "Playbook", perm: "playbook:manage", Icon: IconBook },
      { href: "/admin", label: "Users & roles", perm: "admin:manage_users", Icon: IconUsers },
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
        <span className="nm">Frontdoor</span>
      </Link>

      <nav className="sb-nav">
        {GROUPS.map((g) => {
          const items = g.items.filter((it) => it.perm === null || has(it.perm));
          if (!items.length) return null;
          return (
            <div key={g.label}>
              <div className="sb-group-label">{g.label}</div>
              {items.map(({ href, label, Icon }) => (
                <Link key={href} href={href} className={`sb-link ${active(href) ? "active" : ""}`}>
                  <Icon />
                  <span>{label}</span>
                </Link>
              ))}
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
