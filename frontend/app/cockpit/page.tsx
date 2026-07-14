"use client";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type AssignableUser, type RequestDetail, type RequestSummary } from "../../lib/api";
import { useAuth } from "../../lib/auth";
import { RiskBadge } from "../components/Workflow";

/* ————— which requests sit in the triage cockpit queue —————
   a request is "in play" when it's waiting on a human decision:
   an open approval/redline step, a contract approved-and-ready-to-send,
   or an advice ticket in review awaiting the answer. Snoozed rows hide. */
const isSnoozed = (r: RequestSummary) =>
  !!r.snoozed_until && new Date(r.snoozed_until).getTime() > Date.now();
function inQueue(r: RequestSummary): boolean {
  if (isSnoozed(r)) return false;
  if (r.open_steps > 0) return true;
  if (r.category === "CONTRACT" && r.state === "APPROVED") return true;      // ready to send
  if (r.category === "ADVICE" && r.state === "IN_REVIEW") return true;        // answer awaits
  return false;
}

function LanePill({ lane }: { lane: string | null }) {
  if (!lane) return null;
  const cls = lane === "AUTO" ? "auto" : lane === "ASSISTED" ? "assisted" : "escalated";
  return <span className={`pill ${cls}`}>{lane.toLowerCase()}</span>;
}
function Kbd({ k }: { k: string }) { return <kbd>{k}</kbd>; }

const adviceAwaitsAnswer = (d: RequestDetail) =>
  d.category === "ADVICE" && (d.state === "IN_REVIEW" || d.state === "ROUTED");

type PrimaryKind = "approve-advice" | "write-answer" | "send" | "open-review" | "open";
function primaryFor(d: RequestDetail): { kind: PrimaryKind; label: string; hint: string } {
  if (adviceAwaitsAnswer(d)) {
    return d.resolution_draft
      ? { kind: "approve-advice", label: "Approve answer", hint: "a" }
      : { kind: "write-answer", label: "Write answer", hint: "a" };  // no draft yet — reviewer authors it
  }
  const advice = d.category === "ADVICE";
  if (!advice && d.state === "APPROVED") return { kind: "send", label: "Send for signature", hint: "a" };
  if (!advice && d.open_steps > 0) return { kind: "open-review", label: "Open redline cockpit", hint: "o" };
  return { kind: "open", label: "Open ticket", hint: "o" };
}

export default function Cockpit() {
  const { user, has } = useAuth();
  const canDecide = has("review:decide");
  const canSend = has("request:send");
  const canQueueOps = has("review:decide") || has("intake:manage");

  const [rows, setRows] = useState<RequestSummary[]>([]);
  const [cursor, setCursor] = useState(0);
  const [detail, setDetail] = useState<RequestDetail | null>(null);
  const [staff, setStaff] = useState<AssignableUser[]>([]);
  const [triaged, setTriaged] = useState(0);          // this session's cleared count
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [showReassign, setShowReassign] = useState(false);
  const [showCheats, setShowCheats] = useState(false);
  const [q, setQ] = useState("");
  const [showSearch, setShowSearch] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() =>
    api.listRequests().then((all) => setRows(all.filter(inQueue))).catch(() => setRows([])), []);
  // pause background polling while a dialog/editor is open so a queue reshuffle
  // can't yank the current ticket out from under an in-progress answer
  const pauseRef = useRef(false);
  useEffect(() => { pauseRef.current = editing || showReassign; }, [editing, showReassign]);
  useEffect(() => {
    load();
    api.assignableUsers().then(setStaff).catch(() => setStaff([]));
    const t = setInterval(() => { if (!pauseRef.current) load(); }, 8000);
    return () => clearInterval(t);
  }, [load]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((r) =>
      r.counterparty_name.toLowerCase().includes(needle) || r.ref.toLowerCase().includes(needle) ||
      (r.purpose || "").toLowerCase().includes(needle) || (r.requester_name || "").toLowerCase().includes(needle));
  }, [rows, q]);

  useEffect(() => { setCursor((c) => Math.min(Math.max(c, 0), Math.max(0, shown.length - 1))); }, [shown.length]);

  const current = shown[cursor] ?? null;
  // fetch the full detail whenever the cursor lands on a new ticket
  useEffect(() => {
    setEditing(false); setShowReassign(false);
    if (!current) { setDetail(null); return; }
    let live = true;
    api.getRequest(current.id).then((d) => { if (live) setDetail(d); }).catch(() => { if (live) setDetail(null); });
    return () => { live = false; };
  }, [current?.id]);

  const primary = detail ? primaryFor(detail) : null;

  /* ————— actions ————— */
  const afterResolve = useCallback(async () => {
    setTriaged((n) => n + 1);
    await load();
    setCursor((c) => Math.min(c, Math.max(0, shown.length - 2))); // the cleared row leaves the queue
  }, [load, shown.length]);

  const startEdit = useCallback(() => {
    if (!detail || !adviceAwaitsAnswer(detail) || !canDecide) return;
    setDraft(detail.resolution_draft || "");   // blank when there's no AI draft to start from
    setEditing(true);
  }, [detail, canDecide]);

  const runPrimary = useCallback(async () => {
    if (!detail || !primary || busy) return;
    try {
      setBusy(true);
      if (primary.kind === "approve-advice") {
        if (!canDecide) return;
        await api.resolveAdvice(detail.id, detail.resolution_draft || "");
        await afterResolve();
      } else if (primary.kind === "write-answer") {
        startEdit();  // open a blank editor — nothing to submit until the reviewer writes it
      } else if (primary.kind === "send") {
        if (!canSend) return;
        await api.send(detail.id);
        await afterResolve();
      } else {
        window.location.href = primary.kind === "open-review" ? `/review/${detail.id}` : `/t/${detail.id}`;
      }
    } catch { /* surfaced by the reload; keep the cockpit alive */ } finally { setBusy(false); }
  }, [detail, primary, busy, canDecide, canSend, afterResolve, startEdit]);
  const saveEdit = useCallback(async () => {
    if (!detail || busy || !draft.trim()) return;   // never approve an empty answer
    try { setBusy(true); await api.resolveAdvice(detail.id, draft); setEditing(false); await afterResolve(); }
    catch {} finally { setBusy(false); }
  }, [detail, draft, busy, afterResolve]);

  const snooze = useCallback(async () => {
    if (!current || !canQueueOps || busy) return;
    try { setBusy(true); await api.snoozeRequest(current.id, 24); await afterResolve(); } catch {} finally { setBusy(false); }
  }, [current, canQueueOps, busy, afterResolve]);
  const takeMine = useCallback(async () => {
    if (!current || !user || !canQueueOps || busy) return;
    try { setBusy(true); await api.assignRequest(current.id, user.id); await load(); } catch {} finally { setBusy(false); }
  }, [current, user, canQueueOps, busy, load]);
  const reassignTo = useCallback(async (userId: string) => {
    if (!current || busy) return;
    try { setBusy(true); await api.assignRequest(current.id, userId); setShowReassign(false); await load(); }
    catch {} finally { setBusy(false); }
  }, [current, busy, load]);

  /* ————— keyboard: j/k navigate · a primary · e edit · s snooze · m mine · r reassign · o open · / search · ? help ————— */
  const onKey = useCallback((e: KeyboardEvent) => {
    const el = e.target as HTMLElement | null;
    if (el?.closest?.("input, textarea, select") || e.metaKey || e.ctrlKey) {
      if (e.key === "Escape") { setEditing(false); setShowSearch(false); setQ(""); (el as HTMLElement)?.blur?.(); }
      return;
    }
    // while the cheatsheet is up, only Esc (close) and ? (toggle) do anything
    if (showCheats && e.key !== "Escape" && e.key !== "?") return;
    if (e.key === "Escape") {
      if (showCheats) setShowCheats(false);
      else if (showReassign) setShowReassign(false);
      else if (editing) setEditing(false);
      else if (showSearch) { setShowSearch(false); setQ(""); }
      return;
    }
    if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, shown.length - 1)); }
    else if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (e.key === "a") runPrimary();
    else if (e.key === "e") startEdit();
    else if (e.key === "s") snooze();
    else if (e.key === "m") takeMine();
    else if (e.key === "r" && canQueueOps) setShowReassign((v) => !v);
    else if (e.key === "o" || e.key === "Enter") { if (current) window.location.href = detail && detail.open_steps > 0 && detail.category === "CONTRACT" ? `/review/${current.id}` : `/t/${current.id}`; }
    else if (e.key === "?") setShowCheats((v) => !v);
    else if (e.key === "/") { e.preventDefault(); setShowSearch(true); setTimeout(() => searchRef.current?.focus(), 20); }
  }, [shown.length, runPrimary, startEdit, snooze, takeMine, canQueueOps, current, detail, showCheats, showReassign, editing, showSearch]);
  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  const advice = detail?.category === "ADVICE";
  const pendingChanges = detail?.review?.changes?.filter((c) => c.decision === "PENDING").length ?? 0;

  return (
    <div style={{ position: "relative" }}>
      {/* header status bar */}
      <div className="cockpit-bar">
        <div className="cbar-stats">
          <div>
            <div className="cbar-k">Queue</div>
            <div className="cbar-v">
              {shown.length > 0
                ? <><span style={{ color: "var(--teal)", fontWeight: 700 }} className="mono">{cursor + 1}</span> of {shown.length}</>
                : <span className="faint">Empty</span>}
            </div>
          </div>
          <span className="cbar-div" />
          <div>
            <div className="cbar-k">Triaged this session</div>
            <div className="cbar-v" style={{ color: "var(--good)" }}>{triaged}</div>
          </div>
          <span className="cbar-div" />
          <div>
            <div className="cbar-k">Reviewer</div>
            <div className="cbar-v mono" style={{ fontSize: 12 }}>{user?.name ?? "—"}</div>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {showSearch && (
            <input ref={searchRef} value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="search ref / counterparty / requester" style={{ width: 250, fontSize: 12 }} />
          )}
          <button className="btn sm ghost" onClick={() => setShowCheats(true)}><Kbd k="?" /> help</button>
        </div>
      </div>

      {current && detail ? (
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 14 }}>
          {/* left — the ticket */}
          <div className="card card-pad" style={{ borderLeft: `3px solid ${advice ? "var(--teal)" : "var(--accent)"}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 10 }}>
              <span className="mono" style={{ color: "var(--accent-ink)", fontWeight: 600, fontSize: 13 }}>{detail.ref}</span>
              {!advice && <LanePill lane={detail.lane} />}
              {!advice && <RiskBadge risk={detail.risk} />}
              <span className="pill state">{detail.state.replace(/_/g, " ").toLowerCase()}</span>
              {detail.round > 1 && <span className="pill accent">↺ round {detail.round}</span>}
              {detail.type_label && <span className="pill accent">{detail.type_label.split(" / ")[0]}</span>}
            </div>
            <h1 className="h-serif" style={{ fontSize: 24, margin: "2px 0 6px" }}>
              {advice ? (detail.type_label || "Legal request") : detail.counterparty_name}
            </h1>
            <div className="mono" style={{ fontSize: 11, color: "var(--muted)", marginBottom: 14 }}>
              From {detail.requester_name}
              {detail.assigned_to_name ? ` · Assigned to ${detail.assigned_to_name}` : " · Unassigned"}
              {" · "}{new Date(detail.created_at).toISOString().slice(0, 10)}
            </div>

            {(detail.purpose || detail.details) && (
              <div style={{ marginBottom: 14 }}>
                <div className="kicker" style={{ marginBottom: 6 }}>{advice ? "The question" : "Purpose"}</div>
                <p style={{ fontSize: 14, lineHeight: 1.55, color: "var(--ink)", whiteSpace: "pre-wrap" }}>
                  {advice ? (detail.details || detail.purpose) : detail.purpose}
                </p>
              </div>
            )}

            {detail.triage_reasons?.length > 0 && (
              <div>
                <div className="kicker" style={{ marginBottom: 6 }}>Why it triaged here</div>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5, color: "var(--muted)", lineHeight: 1.6 }}>
                  {detail.triage_reasons.map((t, i) => <li key={i}>{t}</li>)}
                </ul>
              </div>
            )}
          </div>

          {/* right — recommendation + actions */}
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div className="card card-pad">
              <div className="kicker" style={{ marginBottom: 8 }}>
                {advice ? "🤖 Drafted answer — governed proposal" : "Agent recommendation"}
              </div>

              {advice ? (
                editing ? (
                  <>
                    <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={9}
                      style={{ width: "100%", fontSize: 13, lineHeight: 1.5, resize: "vertical" }} />
                    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
                      <button className="btn primary sm" disabled={busy || !draft.trim()} onClick={saveEdit}>Save &amp; approve</button>
                      <button className="btn ghost sm" onClick={() => setEditing(false)}>Cancel</button>
                    </div>
                  </>
                ) : (
                  <>
                    <p style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink)", whiteSpace: "pre-wrap",
                      maxHeight: 260, overflowY: "auto" }}>
                      {detail.resolution_draft || <span className="faint">No draft yet — write the answer to resolve this request.</span>}
                    </p>
                    {canDecide && (
                      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
                        {detail.resolution_draft ? (
                          <>
                            <button className="btn primary sm" disabled={busy} onClick={runPrimary}><Kbd k="a" /> Approve answer</button>
                            <button className="btn sm" disabled={busy} onClick={startEdit}><Kbd k="e" /> Edit</button>
                          </>
                        ) : (
                          <button className="btn primary sm" disabled={busy} onClick={startEdit}><Kbd k="a" /> Write answer</button>
                        )}
                      </div>
                    )}
                    {!canDecide && <p className="faint" style={{ fontSize: 12, marginTop: 8 }}>You can review but not approve — needs a reviewer.</p>}
                  </>
                )
              ) : (
                <>
                  <div style={{ display: "flex", gap: 14, marginBottom: 10, flexWrap: "wrap" }}>
                    <div>
                      <div className="cbar-k">Redlines pending</div>
                      <div className="tnum" style={{ fontSize: 20, fontWeight: 700, color: pendingChanges ? "var(--warn)" : "var(--good)" }}>{pendingChanges}</div>
                    </div>
                    <div>
                      <div className="cbar-k">Open steps</div>
                      <div className="tnum" style={{ fontSize: 20, fontWeight: 700, color: detail.open_steps ? "var(--warn)" : "var(--good)" }}>{detail.open_steps}</div>
                    </div>
                    {detail.risk_band && (
                      <div>
                        <div className="cbar-k">Risk</div>
                        <div className="tnum" style={{ fontSize: 20, fontWeight: 700 }}>{detail.risk_band}</div>
                      </div>
                    )}
                  </div>
                  <p className="muted" style={{ fontSize: 12.5, lineHeight: 1.5, marginBottom: 12 }}>
                    {detail.state === "APPROVED"
                      ? "Ladder cleared and every redline decided — the counter-proposal is ready to send for signature."
                      : `${pendingChanges} agent-proposed redline${pendingChanges === 1 ? "" : "s"} await your decision in the redline cockpit.`}
                  </p>
                  {primary && (
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      {primary.kind === "send" ? (
                        canSend && <button className="btn primary sm" disabled={busy} onClick={runPrimary}><Kbd k="a" /> {primary.label}</button>
                      ) : (
                        <Link href={`/review/${detail.id}`} className="btn primary sm"><Kbd k="o" /> {primary.label} →</Link>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* other actions */}
            <div className="card card-pad">
              <div className="kicker" style={{ marginBottom: 8 }}>Other actions</div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                <Link href={`/t/${detail.id}`} className="btn sm ghost"><Kbd k="o" /> Open ticket</Link>
                {canQueueOps && <button className="btn sm ghost" onClick={() => setShowReassign((v) => !v)}><Kbd k="r" /> Reassign</button>}
                {canQueueOps && <button className="btn sm ghost" onClick={takeMine}><Kbd k="m" /> Assign to me</button>}
                {canQueueOps && <button className="btn sm ghost" onClick={snooze}><Kbd k="s" /> Snooze 1d</button>}
              </div>
              {showReassign && (
                <div style={{ marginTop: 10, borderTop: "1px solid var(--line)", paddingTop: 10 }}>
                  <div className="cbar-k" style={{ marginBottom: 6 }}>Reassign to</div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3, maxHeight: 200, overflowY: "auto" }}>
                    {staff.map((u) => (
                      <button key={u.id} className="linkish" style={{ textAlign: "left", padding: "5px 6px", fontSize: 12.5 }}
                        disabled={busy} onClick={() => reassignTo(u.id)}>
                        {u.name} <span className="faint mono" style={{ fontSize: 10 }}>· {u.role.replace(/_/g, " ")}</span>
                      </button>
                    ))}
                    {staff.length === 0 && <span className="faint" style={{ fontSize: 12 }}>No assignable staff.</span>}
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="card card-pad" style={{ textAlign: "center", padding: 40, borderLeft: "3px solid var(--good)" }}>
          <div className="h-serif" style={{ fontSize: 26, color: "var(--ink)", marginBottom: 6 }}>{q ? "No matches" : "Queue empty"}</div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
            {q ? "Try a different search term." : "Nothing awaiting triage. Inbox zero."}
          </p>
          <div className="mono faint" style={{ fontSize: 11 }}>Triaged this session: <span style={{ color: "var(--good)", fontWeight: 600 }}>{triaged}</span></div>
        </div>
      )}

      {/* sticky bottom hint bar */}
      {current && (
        <div className="cockpit-hints">
          <div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center" }}>
            <span><Kbd k="j" /><Kbd k="k" /> navigate</span>
            <span><Kbd k="a" /> {primary?.label.toLowerCase() ?? "primary"}</span>
            {advice && <span><Kbd k="e" /> edit</span>}
            <span><Kbd k="o" /> open</span>
            <span><Kbd k="s" /> snooze</span>
            <span><Kbd k="m" /> mine</span>
            <span><Kbd k="?" /> all shortcuts</span>
          </div>
          <span>keyboard-first · press <Kbd k="?" /> anytime</span>
        </div>
      )}

      {/* cheatsheet */}
      {showCheats && (
        <div className="modal-scrim" onClick={() => setShowCheats(false)}>
          <div className="card card-pad" style={{ width: "min(440px, 92vw)" }} onClick={(e) => e.stopPropagation()}>
            <div className="kicker" style={{ marginBottom: 10 }}>Keyboard shortcuts</div>
            {[
              ["j / ↓", "Next ticket"], ["k / ↑", "Previous ticket"],
              ["a", "Primary action (approve answer / send / open review)"],
              ["e", "Edit the drafted answer (advice)"], ["o / ↵", "Open the ticket"],
              ["r", "Reassign"], ["m", "Assign to me"], ["s", "Snooze 1 day"],
              ["/", "Search the queue"], ["?", "Toggle this sheet"], ["Esc", "Close / cancel"],
            ].map(([k, d]) => (
              <div key={k} style={{ display: "flex", gap: 12, padding: "5px 0", fontSize: 13, borderBottom: "1px dashed var(--line)" }}>
                <span className="mono" style={{ minWidth: 64, color: "var(--teal)" }}>{k}</span>
                <span style={{ color: "var(--ink)" }}>{d}</span>
              </div>
            ))}
            <button className="btn sm ghost" style={{ marginTop: 12 }} onClick={() => setShowCheats(false)}>Close</button>
          </div>
        </div>
      )}
    </div>
  );
}
