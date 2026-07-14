"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type RequestSummary } from "../../lib/api";
import { useAuth } from "../../lib/auth";

type Cmd = { id: string; label: string; hint?: string; run: () => void };

/* ⌘K / Ctrl-K — navigate anywhere, jump to any request by ref or counterparty.
   Chat is for thinking; the palette is for moving. */
export function CommandPalette() {
  const router = useRouter();
  const { user, has } = useAuth();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [idx, setIdx] = useState(0);
  const [reqs, setReqs] = useState<RequestSummary[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      } else if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    setQ(""); setIdx(0);
    setTimeout(() => inputRef.current?.focus(), 30);
    api.listRequests().then(setReqs).catch(() => setReqs([]));
  }, [open]);

  const go = useCallback((href: string) => { setOpen(false); router.push(href); }, [router]);

  const commands = useMemo<Cmd[]>(() => {
    const nav: Cmd[] = [
      { id: "nav-home", label: "Go to Dashboard", run: () => go("/") },
      ...(has("request:read_all") ? [
        { id: "nav-inbox", label: "Go to Legal inbox", hint: "triage queue", run: () => go("/inbox") },
        { id: "nav-contracts", label: "Go to Contracts", hint: "renewals & obligations", run: () => go("/contracts") },
        { id: "nav-sla", label: "Go to SLA & metrics", run: () => go("/sla") },
        { id: "nav-inbound", label: "Review their paper", hint: "inbound redline", run: () => go("/inbound") },
        { id: "nav-email", label: "Email intake", run: () => go("/email-sim") },
      ] : []),
      ...(has("request:create") ? [
        { id: "new", label: "New request…", hint: "NDA or ask legal", run: () => go("/new") },
        { id: "chat", label: "Ask legal (chat)", run: () => go("/chat") },
      ] : []),
      ...(has("intake:manage") ? [
        { id: "nav-routing", label: "Routing rules", hint: "admin", run: () => go("/admin/routing") },
      ] : []),
      ...(has("playbook:manage") ? [
        { id: "nav-playbook", label: "Playbook", hint: "admin", run: () => go("/admin/playbook") },
      ] : []),
    ];
    const needle = q.trim().toLowerCase();
    const reqCmds: Cmd[] = (needle.length >= 2 ? reqs : [])
      .filter((r) =>
        r.ref.toLowerCase().includes(needle) ||
        r.counterparty_name.toLowerCase().includes(needle) ||
        (r.type_label || "").toLowerCase().includes(needle))
      .slice(0, 6)
      .map((r) => ({
        id: `req-${r.id}`,
        label: `${r.ref} — ${r.counterparty_name}`,
        hint: `${(r.type_label || r.type)} · ${r.state.replace(/_/g, " ").toLowerCase()}`,
        run: () => go(has("request:read_all") ? `/review/${r.id}` : `/r/${r.id}`),
      }));
    const filteredNav = needle
      ? nav.filter((c) => c.label.toLowerCase().includes(needle) || (c.hint || "").toLowerCase().includes(needle))
      : nav;
    return [...reqCmds, ...filteredNav];
  }, [q, reqs, has, go]);

  useEffect(() => { setIdx((i) => Math.min(i, Math.max(0, commands.length - 1))); }, [commands.length]);

  if (!user || !open) return null;
  return (
    <div className="cp-overlay" onClick={() => setOpen(false)}>
      <div className="cp-panel card" onClick={(e) => e.stopPropagation()}>
        <input
          ref={inputRef} className="cp-input" value={q} placeholder="Type a command, a ref, or a counterparty…"
          onChange={(e) => { setQ(e.target.value); setIdx(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(i + 1, commands.length - 1)); }
            else if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(i - 1, 0)); }
            else if (e.key === "Enter" && commands[idx]) commands[idx].run();
          }}
        />
        <div className="cp-list">
          {commands.map((c, i) => (
            <button key={c.id} className={`cp-item ${i === idx ? "on" : ""}`}
              onMouseEnter={() => setIdx(i)} onClick={c.run}>
              <span>{c.label}</span>
              {c.hint && <span className="faint" style={{ fontSize: 12 }}>{c.hint}</span>}
            </button>
          ))}
          {commands.length === 0 && <div className="faint" style={{ padding: 14, fontSize: 13 }}>Nothing matches.</div>}
        </div>
        <div className="cp-foot faint">↑↓ navigate · ↵ open · esc close</div>
      </div>
    </div>
  );
}
