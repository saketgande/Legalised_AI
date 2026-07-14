"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type AssignableUser, type RequestSummary } from "../../lib/api";
import { useAuth } from "../../lib/auth";

const CLOSED = new Set(["SIGNED", "FILED", "EXECUTED", "CANCELLED"]);

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return <span className="pill state">—</span>;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane.toLowerCase()}</span>;
}

function PrioDot({ p }: { p: string }) {
  if (p === "NORMAL" || p === "LOW") return null;
  const c = p === "URGENT" ? "var(--crit)" : "var(--warn)";
  return <span title={`${p.toLowerCase()} priority`} style={{
    display: "inline-block", width: 7, height: 7, borderRadius: "50%",
    background: c, marginRight: 6, verticalAlign: "middle",
  }} />;
}

function ageDays(iso: string): number {
  return Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
}
const needsMe = (r: RequestSummary) => r.open_steps > 0 || r.state === "APPROVED";
const isOverdue = (r: RequestSummary) => ageDays(r.created_at) >= 5 && !CLOSED.has(r.state);
const isSnoozed = (r: RequestSummary) =>
  !!r.snoozed_until && new Date(r.snoozed_until).getTime() > Date.now();

type Filter = "all" | "needs" | "mine" | "inbound" | "overdue" | "snoozed";
type SavedView = { name: string; filter: Filter; q: string; type: string };
const VIEWS_KEY = "fd-inbox-views";

export default function Inbox() {
  const { user } = useAuth();
  const [rows, setRows] = useState<RequestSummary[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [cursor, setCursor] = useState(0);
  const [staff, setStaff] = useState<AssignableUser[]>([]);
  const [views, setViews] = useState<SavedView[]>([]);
  const [busy, setBusy] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const load = () => api.listRequests().then(setRows).catch(() => setRows([]));
  useEffect(() => {
    load();
    api.assignableUsers().then(setStaff).catch(() => setStaff([]));
    try { setViews(JSON.parse(localStorage.getItem(VIEWS_KEY) || "[]")); } catch {}
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, []);

  const types = useMemo(() => {
    const m = new Map<string, string>();
    rows.forEach((r) => m.set(r.type, r.type_label || r.type));
    return [...m.entries()];
  }, [rows]);

  const counts = useMemo(() => ({
    all: rows.filter((r) => !isSnoozed(r)).length,
    needs: rows.filter((r) => needsMe(r) && !isSnoozed(r)).length,
    mine: rows.filter((r) => r.assigned_to_user_id === user?.id && !isSnoozed(r)).length,
    inbound: rows.filter((r) => r.direction === "INBOUND" && !isSnoozed(r)).length,
    overdue: rows.filter((r) => isOverdue(r) && !isSnoozed(r)).length,
    snoozed: rows.filter(isSnoozed).length,
  }), [rows, user]);

  const shown = useMemo(() => {
    let out = rows;
    if (filter === "snoozed") out = out.filter(isSnoozed);
    else {
      out = out.filter((r) => !isSnoozed(r)); // snoozed hide from every other view
      if (filter === "needs") out = out.filter(needsMe);
      else if (filter === "mine") out = out.filter((r) => r.assigned_to_user_id === user?.id);
      else if (filter === "inbound") out = out.filter((r) => r.direction === "INBOUND");
      else if (filter === "overdue") out = out.filter(isOverdue);
    }
    if (typeFilter) out = out.filter((r) => r.type === typeFilter);
    const needle = q.trim().toLowerCase();
    if (needle) out = out.filter((r) =>
      r.counterparty_name.toLowerCase().includes(needle) || r.ref.toLowerCase().includes(needle) ||
      (r.assigned_to_name || "").toLowerCase().includes(needle));
    return out;
  }, [rows, filter, typeFilter, q, user]);

  useEffect(() => { setCursor((c) => Math.min(c, Math.max(0, shown.length - 1))); }, [shown.length]);

  /* ————— single-key triage: j/k move · enter open · x select · m mine · s snooze ————— */
  const onKey = useCallback((e: KeyboardEvent) => {
    const tag = (e.target as HTMLElement)?.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.metaKey || e.ctrlKey) return;
    const cur = shown[cursor];
    if (e.key === "j") setCursor((c) => Math.min(c + 1, shown.length - 1));
    else if (e.key === "k") setCursor((c) => Math.max(c - 1, 0));
    else if (e.key === "Enter" && cur) window.location.href = `/review/${cur.id}`;
    else if (e.key === "x" && cur) {
      setSel((s) => { const n = new Set(s); n.has(cur.id) ? n.delete(cur.id) : n.add(cur.id); return n; });
    } else if (e.key === "m" && cur && user) {
      api.assignRequest(cur.id, user.id).then(load).catch(() => {});
    } else if (e.key === "s" && cur) {
      api.snoozeRequest(cur.id, filter === "snoozed" ? null : 24).then(load).catch(() => {});
    } else if (e.key === "/") {
      e.preventDefault();
      searchRef.current?.focus();
    } else return;
  }, [shown, cursor, user, filter]);
  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  /* ————— saved views (local, per browser) ————— */
  function saveView() {
    const name = prompt("Name this view:");
    if (!name) return;
    const next = [...views.filter((v) => v.name !== name), { name, filter, q, type: typeFilter }];
    setViews(next);
    localStorage.setItem(VIEWS_KEY, JSON.stringify(next));
  }
  function applyView(v: SavedView) { setFilter(v.filter); setQ(v.q); setTypeFilter(v.type); }
  function dropView(name: string) {
    const next = views.filter((v) => v.name !== name);
    setViews(next);
    localStorage.setItem(VIEWS_KEY, JSON.stringify(next));
  }

  /* ————— bulk actions ————— */
  async function bulk(action: "assign" | "snooze" | "unsnooze", extra: Record<string, unknown> = {}) {
    if (sel.size === 0) return;
    setBusy(true);
    try {
      await api.bulkAction({ ids: [...sel], action, ...extra } as any);
      setSel(new Set());
      await load();
    } catch {} finally { setBusy(false); }
  }

  const seg = (key: Filter, label: string) => (
    <button className={filter === key ? "on" : ""} onClick={() => setFilter(key)}>
      {label} <span className="tnum" style={{ opacity: 0.6 }}>{counts[key]}</span>
    </button>
  );
  const allShownSelected = shown.length > 0 && shown.every((r) => sel.has(r.id));

  return (
    <div>
      <div className="page-head">
        <div className="page-head-row">
          <div>
            <p className="kicker">Legal inbox</p>
            <h1>Triage queue</h1>
          </div>
          <span className="muted" style={{ fontSize: 12 }}>
            <kbd>j</kbd>/<kbd>k</kbd> move · <kbd>↵</kbd> open · <kbd>x</kbd> select · <kbd>m</kbd> mine · <kbd>s</kbd> snooze · <kbd>/</kbd> search
          </span>
        </div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 12, alignItems: "center", flexWrap: "wrap" }}>
        <div className="seg">
          {seg("all", "All")}
          {seg("needs", "Needs me")}
          {seg("mine", "My queue")}
          {seg("inbound", "Inbound")}
          {seg("overdue", "Overdue")}
          {seg("snoozed", "Snoozed")}
        </div>
        <select value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)} style={{ width: 170 }}>
          <option value="">All types</option>
          {types.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <span style={{ flex: 1 }} />
        <input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…  ( / )"
          style={{ width: 200 }} />
        <div className="views-dd">
          <details>
            <summary className="btn sm ghost">Views ▾</summary>
            <div className="views-pop card">
              {views.length === 0 && <div className="faint" style={{ padding: "8px 10px", fontSize: 12 }}>No saved views yet.</div>}
              {views.map((v) => (
                <div key={v.name} className="views-row">
                  <button className="linkish" onClick={() => applyView(v)}>{v.name}</button>
                  <button className="icon-x" title="Delete view" onClick={() => dropView(v.name)}>✕</button>
                </div>
              ))}
              <div style={{ borderTop: "1px solid var(--line-2)", padding: "6px 10px" }}>
                <button className="linkish" onClick={saveView}>+ Save current view</button>
              </div>
            </div>
          </details>
        </div>
        <Link href="/new" className="btn primary">+ New request</Link>
      </div>

      {sel.size > 0 && (
        <div className="bulkbar">
          <span className="tnum" style={{ fontWeight: 640 }}>{sel.size} selected</span>
          <span className="faint">·</span>
          <select disabled={busy} defaultValue="" onChange={(e) => { if (e.target.value) { bulk("assign", { user_id: e.target.value }); e.target.value = ""; } }}>
            <option value="" disabled>Assign to…</option>
            {staff.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <button className="btn sm" disabled={busy} onClick={() => bulk("snooze", { hours: 24 })}>Snooze 1d</button>
          <button className="btn sm" disabled={busy} onClick={() => bulk("unsnooze")}>Unsnooze</button>
          <span style={{ flex: 1 }} />
          <button className="btn sm ghost" onClick={() => setSel(new Set())}>Clear</button>
        </div>
      )}

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="tbl">
            <thead>
              <tr>
                <th style={{ width: 30 }}>
                  <input type="checkbox" checked={allShownSelected}
                    onChange={() => setSel(allShownSelected ? new Set() : new Set(shown.map((r) => r.id)))} />
                </th>
                <th>Ref</th>
                <th>Subject</th>
                <th>Type</th>
                <th>Lane</th>
                <th>State</th>
                <th>Assignee</th>
                <th>Age</th>
                <th>To do</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => {
                const inbound = r.direction === "INBOUND";
                const over = isOverdue(r);
                const age = ageDays(r.created_at);
                const advice = r.category === "ADVICE";
                return (
                  <tr key={r.id}
                    className={`${needsMe(r) || over ? "sev" : ""} ${i === cursor ? "cursor-row" : ""}`}
                    style={{ cursor: "pointer" }}
                    onClick={(e) => {
                      if ((e.target as HTMLElement).tagName === "INPUT") return;
                      window.location.href = `/review/${r.id}`;
                    }}>
                    <td onClick={(e) => e.stopPropagation()}>
                      <input type="checkbox" checked={sel.has(r.id)}
                        onChange={() => setSel((s) => { const n = new Set(s); n.has(r.id) ? n.delete(r.id) : n.add(r.id); return n; })} />
                    </td>
                    <td className="ref">{r.ref}</td>
                    <td className="cp">
                      <PrioDot p={r.priority} />
                      {advice ? (r.purpose || r.type_label) : r.counterparty_name}
                      {inbound && <span className="sub">their paper</span>}
                      {isSnoozed(r) && <span className="sub">zzz until {new Date(r.snoozed_until!).toLocaleDateString()}</span>}
                    </td>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>{r.type_label || (r.nda_type === "MUTUAL" ? "NDA · mutual" : "NDA · one-way")}</td>
                    <td><LanePill lane={r.lane} /></td>
                    <td><span className="pill state">{r.state.replace(/_/g, " ").toLowerCase()}</span></td>
                    <td className="muted" style={{ whiteSpace: "nowrap" }}>{r.assigned_to_name || <span className="faint">—</span>}</td>
                    <td><span className={`age ${over ? "over" : ""}`}>{age === 0 ? "today" : `${age}d`}{over && " ⚠"}</span></td>
                    <td>
                      {r.open_steps > 0 ? (
                        <span className="todo-act">{inbound ? `${r.open_steps} to decide` : advice ? "answer" : `${r.open_steps} approval${r.open_steps > 1 ? "s" : ""}`} →</span>
                      ) : r.state === "APPROVED" && !advice ? (
                        <span className="todo-ready">ready to send</span>
                      ) : advice && r.state === "IN_REVIEW" ? (
                        <span className="todo-act">answer →</span>
                      ) : (
                        <span className="faint">—</span>
                      )}
                    </td>
                  </tr>
                );
              })}
              {shown.length === 0 && (
                <tr><td colSpan={9} className="muted" style={{ padding: 30, textAlign: "center" }}>
                  {rows.length === 0 ? <>No requests yet. <Link href="/new" style={{ color: "var(--accent)" }}>File one →</Link></> : "Nothing matches this filter."}
                </td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
