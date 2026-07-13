"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type MailboxConfig, type PlaybookSummary, type PollResult, type RequestSummary } from "../../lib/api";
import { useAuth } from "../../lib/auth";

/* ────────────────────────── connected inbox ────────────────────────── */
const PRESETS: Record<string, { host: string; port: number }> = {
  Gmail: { host: "imap.gmail.com", port: 993 },
  "Outlook / M365": { host: "outlook.office365.com", port: 993 },
  "Yahoo": { host: "imap.mail.yahoo.com", port: 993 },
};

function rel(iso?: string | null) {
  if (!iso) return "never";
  const s = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function MailboxCard() {
  const [cfg, setCfg] = useState<MailboxConfig | null>(null);
  const [books, setBooks] = useState<PlaybookSummary[]>([]);
  const [form, setForm] = useState({
    imap_host: "", imap_port: 993, use_ssl: true, username: "", password: "",
    folder: "INBOX", active: true, default_playbook_id: "",
  });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [test, setTest] = useState<string | null>(null);
  const [poll, setPoll] = useState<PollResult | null>(null);

  async function load() {
    const c = await api.getMailbox();
    setCfg(c);
    if (c.configured) {
      setForm((f) => ({
        ...f, imap_host: c.imap_host ?? "", imap_port: c.imap_port ?? 993, use_ssl: c.use_ssl ?? true,
        username: c.username ?? "", password: "", folder: c.folder ?? "INBOX", active: c.active ?? true,
        default_playbook_id: c.default_playbook_id ?? "",
      }));
    }
  }
  useEffect(() => {
    load().catch((e) => setErr(String(e)));
    api.listPlaybooks().then(setBooks).catch(() => setBooks([]));
  }, []);

  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

  async function save() {
    setBusy("save"); setErr(null); setMsg(null);
    try {
      const body: Record<string, unknown> = {
        imap_host: form.imap_host, imap_port: Number(form.imap_port), use_ssl: form.use_ssl,
        username: form.username, folder: form.folder, active: form.active,
        default_playbook_id: form.default_playbook_id || null,
      };
      if (form.password) body.password = form.password;       // omit -> keep stored secret
      await api.saveMailbox(body);
      setMsg("Saved. The poller checks this inbox automatically while it’s active.");
      setForm((f) => ({ ...f, password: "" }));
      await load();
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(null); }
  }

  async function doTest() {
    setBusy("test"); setErr(null); setMsg(null); setTest(null);
    try {
      const r = await api.testMailbox();
      setTest(r.ok ? `✓ Connected to ${r.folder} — ${r.total} messages, ${r.unseen} unread.` : `✕ ${r.error}`);
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(null); }
  }

  async function doPoll() {
    setBusy("poll"); setErr(null); setMsg(null); setPoll(null);
    try {
      const r = await api.pollMailbox();
      setPoll(r);
      if (!r.ok) setErr(r.error || "poll failed");
      await load();
    } catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(null); }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect this inbox? Polling stops; filed requests stay.")) return;
    setBusy("del"); setErr(null);
    try { await api.deleteMailbox(); setCfg({ configured: false }); setPoll(null); setTest(null); setMsg("Inbox disconnected."); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); }
    finally { setBusy(null); }
  }

  return (
    <div className="card card-pad" style={{ marginBottom: 22 }}>
      <div className="page-head-row" style={{ marginBottom: 14 }}>
        <div className="kicker">Connected inbox</div>
        {cfg?.configured && (
          <span className={`pill ${cfg.active ? "good" : "state"}`}>
            <span className="dot" />{cfg.active ? "Polling active" : "Paused"}
          </span>
        )}
      </div>

      {cfg?.configured && (
        <div className="stat-grid" style={{ marginBottom: 16 }}>
          <div className="stat"><div className="lbl">Last polled</div><div className="val tnum" style={{ fontSize: 18 }}>{rel(cfg.last_polled_at)}</div></div>
          <div className="stat"><div className="lbl">Messages filed (lifetime)</div><div className="val tnum" style={{ fontSize: 18 }}>{cfg.ingested_count ?? 0}</div></div>
          <div className="stat"><div className="lbl">Last run</div><div className="val" style={{ fontSize: 15 }}>{cfg.last_result?.polled != null ? `${cfg.last_result.ingested}/${cfg.last_result.polled} filed` : "—"}</div></div>
        </div>
      )}

      {cfg?.last_error && <div className="notice warn" style={{ marginBottom: 12 }}>Last poll error: {cfg.last_error}</div>}

      <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
        <span className="faint" style={{ fontSize: 12, alignSelf: "center" }}>Quick fill:</span>
        {Object.entries(PRESETS).map(([name, p]) => (
          <button key={name} type="button" className="btn sm ghost" onClick={() => setForm((f) => ({ ...f, imap_host: p.host, imap_port: p.port, use_ssl: true }))}>{name}</button>
        ))}
      </div>

      <div className="row2">
        <div className="field"><label>IMAP host</label><input value={form.imap_host} onChange={(e) => set("imap_host", e.target.value)} placeholder="imap.gmail.com" /></div>
        <div className="field"><label>Port</label><input type="number" value={form.imap_port} onChange={(e) => set("imap_port", e.target.value)} /></div>
      </div>
      <div className="row2">
        <div className="field"><label>Inbox address / username</label><input value={form.username} onChange={(e) => set("username", e.target.value)} placeholder="legal@yourco.com" /></div>
        <div className="field">
          <label>Password / app password</label>
          <input type="password" value={form.password} onChange={(e) => set("password", e.target.value)}
            placeholder={cfg?.configured ? "•••••• (unchanged)" : "app-specific password"} />
        </div>
      </div>
      <div className="row2">
        <div className="field"><label>Folder</label><input value={form.folder} onChange={(e) => set("folder", e.target.value)} /></div>
        <div className="field"><label>Review new mail against playbook</label>
          <select value={form.default_playbook_id} onChange={(e) => set("default_playbook_id", e.target.value)}>
            <option value="">Org default</option>
            {books.map((b) => <option key={b.id} value={b.id}>{b.name}{b.active ? " · default" : ""}</option>)}
          </select>
        </div>
      </div>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, margin: "2px 0 14px" }}>
        <input type="checkbox" checked={form.active} onChange={(e) => set("active", e.target.checked)} style={{ width: "auto" }} />
        Poll this inbox automatically
      </label>

      <span className="hint" style={{ display: "block", marginBottom: 14 }}>
        Use a dedicated intake mailbox with an app password. The password is sealed before storage and never shown again.
      </span>

      {err && <div className="notice warn" style={{ marginBottom: 12 }}>{err}</div>}
      {msg && <div className="notice good" style={{ marginBottom: 12 }}>{msg}</div>}
      {test && <div className={`notice ${test.startsWith("✓") ? "good" : "warn"}`} style={{ marginBottom: 12 }}>{test}</div>}

      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        <button className="btn primary" disabled={!!busy} onClick={save}>{busy === "save" ? "Saving…" : cfg?.configured ? "Save changes" : "Connect inbox"}</button>
        {cfg?.configured && <button className="btn" disabled={!!busy} onClick={doTest}>{busy === "test" ? "Testing…" : "Test connection"}</button>}
        {cfg?.configured && <button className="btn" disabled={!!busy} onClick={doPoll}>{busy === "poll" ? "Polling…" : "Poll now"}</button>}
        {cfg?.configured && <button className="btn ghost" disabled={!!busy} style={{ color: "var(--crit)" }} onClick={disconnect}>Disconnect</button>}
      </div>

      {poll && (
        <div style={{ marginTop: 16 }}>
          <div className="kicker" style={{ marginBottom: 8 }}>This poll · {poll.ingested} filed of {poll.polled} new</div>
          {poll.messages.length === 0 ? (
            <p className="muted" style={{ fontSize: 13 }}>No new messages in the inbox.</p>
          ) : (
            <div className="card" style={{ overflow: "hidden" }}>
              <table className="tbl">
                <thead><tr><th>From</th><th>Subject</th><th>Filed as</th><th></th></tr></thead>
                <tbody>
                  {poll.messages.map((m) => (
                    <tr key={m.uid}>
                      <td className="ref">{m.from}</td>
                      <td>{m.subject || <span className="faint">(no subject)</span>}</td>
                      <td>
                        {m.error ? <span className="pill crit">error</span>
                          : m.created ? <span className={`pill ${m.direction === "INBOUND" ? "escalated" : "auto"}`}>{m.classified}</span>
                          : <span className="pill state">needs triage</span>}
                      </td>
                      <td>{m.request_id && <Link className="btn sm ghost" href={m.direction === "INBOUND" ? `/review/${m.request_id}` : `/r/${m.request_id}`}>{m.ref} →</Link>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ────────────────────────── simulator (no creds needed) ────────────────────────── */
const SAMPLES = {
  outbound: { from_email: "jordan@bigco.example", from_name: "Jordan Lee", subject: "Need an NDA",
    body: "Hi legal — can you set up a mutual NDA with Umbrella Corp for a sales evaluation? 12-month term is fine. Thanks!" },
  inbound: { from_email: "legal@globex.example", from_name: "Globex Legal", subject: "Our NDA for your signature",
    body: "1. Term\nThis Agreement remains in effect for sixty (60) months.\n2. Governing Law\nGoverned by the laws of England and Wales.\n3. Limitation of Liability\nLiability shall not exceed the fees paid in the three (3) months preceding the claim." },
};

function SimulatorCard() {
  const [form, setForm] = useState(SAMPLES.outbound);
  const [result, setResult] = useState<{ created: boolean; classified: string; request?: RequestSummary; reply?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const set = (k: string, v: string) => setForm((f) => ({ ...f, [k]: v }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null); setResult(null);
    try { setResult(await api.emailWebhook(form)); }
    catch (e2) { setErr(String(e2).replace(/^Error:\s*/, "")); }
    finally { setBusy(false); }
  }

  return (
    <div className="card card-pad">
      <div className="kicker" style={{ marginBottom: 4 }}>Simulator · no inbox needed</div>
      <p className="muted" style={{ fontSize: 13, marginTop: 0, marginBottom: 14 }}>
        Deliver a test email to the same understand-then-file pipeline the real poller uses — handy for a demo
        without connecting a mailbox.
      </p>

      <div style={{ display: "flex", gap: 8, marginBottom: 14 }}>
        <button className="btn sm ghost" onClick={() => setForm(SAMPLES.outbound)}>Load: request email</button>
        <button className="btn sm ghost" onClick={() => setForm(SAMPLES.inbound)}>Load: their NDA email</button>
      </div>

      <form onSubmit={submit}>
        <div className="row2">
          <div className="field"><label>From (email)</label><input value={form.from_email} onChange={(e) => set("from_email", e.target.value)} /></div>
          <div className="field"><label>From (name)</label><input value={form.from_name} onChange={(e) => set("from_name", e.target.value)} /></div>
        </div>
        <div className="field"><label>Subject</label><input value={form.subject} onChange={(e) => set("subject", e.target.value)} /></div>
        <div className="field">
          <label>Body</label>
          <textarea value={form.body} onChange={(e) => set("body", e.target.value)} rows={8}
            style={{ fontFamily: "var(--mono)", fontSize: 12.5, lineHeight: 1.55 }} />
        </div>
        {err && <div className="notice warn" style={{ marginBottom: 12 }}>{err}</div>}
        <button className="btn primary" disabled={busy} type="submit">{busy ? "Processing…" : "Deliver test email"}</button>
      </form>

      {result && (
        <div className="notice info" style={{ marginTop: 14, display: "block" }}>
          <div className="kicker" style={{ marginBottom: 6 }}>Classified {result.classified}</div>
          {result.created && result.request ? (
            <div>
              Created <b>{result.request.ref}</b> — {result.request.direction === "INBOUND" ? "counterparty paper queued for redline review" : `${result.request.lane} lane`} · {result.request.counterparty_name}{" "}
              <Link style={{ color: "var(--accent-ink)", fontWeight: 600 }} href={result.request.direction === "INBOUND" ? `/review/${result.request.id}` : `/r/${result.request.id}`}>
                Open {result.request.ref} →
              </Link>
            </div>
          ) : (
            <span className="muted">{result.reply}</span>
          )}
        </div>
      )}
    </div>
  );
}

export default function EmailIntake() {
  const { has } = useAuth();
  const canManage = has("intake:manage");
  return (
    <div>
      <div className="page-head">
        <p className="kicker">Intake · email channel</p>
        <h1>Email intake</h1>
        <p className="sub">
          Connect a real legal inbox and the platform polls it: every message that arrives is understood —
          a request for an NDA vs. a counterparty’s paper to review — and filed through the same pipeline,
          on the same audit chain, automatically.
        </p>
      </div>
      {canManage
        ? <MailboxCard />
        : <div className="notice info" style={{ marginBottom: 22, display: "block" }}>Connecting a mailbox needs the <b>intake:manage</b> permission (admin, GC, or legal-ops). You can still try the simulator below.</div>}
      <SimulatorCard />
    </div>
  );
}
