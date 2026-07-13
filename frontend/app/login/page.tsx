"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useAuth } from "../../lib/auth";

const DEMO = [
  { email: "admin@northwind.example", role: "Admin — everything" },
  { email: "priya.nair@northwind.example", role: "GC — approves any deviation" },
  { email: "dana.osei@northwind.example", role: "VP Legal — approves up to VP rung" },
  { email: "marcus.reid@northwind.example", role: "Attorney — reviews, can't clear GC deviations" },
  { email: "sam.carter@northwind.example", role: "Requester — files & tracks own NDAs" },
  { email: "val.ng@northwind.example", role: "Viewer — read-only" },
];

export default function Login() {
  const { login } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("priya.nair@northwind.example");
  const [password, setPassword] = useState("demo1234");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true); setErr(null);
    try { await login(email, password); router.push("/"); }
    catch (e) {
      const msg = e instanceof Error ? e.message : "";
      setErr(msg && !/unauthenticated/i.test(msg) ? msg : "Invalid email or password.");
      setBusy(false);
    }
  }

  return (
    <div className="container narrow" style={{ maxWidth: 460, paddingTop: 60 }}>
      <div className="brand" style={{ marginBottom: 18 }}>
        <span className="mk">F</span><span style={{ fontWeight: 700, fontSize: 18 }}>Frontdoor</span>
      </div>
      <h1 className="h-serif" style={{ fontSize: 26, margin: "0 0 6px" }}>Sign in</h1>
      <p className="muted" style={{ marginBottom: 22, fontSize: 14 }}>
        Your role decides what you can do — and which deviations you can approve.
      </p>

      <form onSubmit={submit} className="card" style={{ padding: 22, marginBottom: 18 }}>
        <div className="field">
          <label>Email</label>
          <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" required />
        </div>
        <div className="field">
          <label>Password</label>
          <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" required />
        </div>
        {err && <div className="notice warn" style={{ marginBottom: 14 }}>{err}</div>}
        <button className="btn primary" style={{ width: "100%" }} disabled={busy} type="submit">
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="card" style={{ padding: 16 }}>
        <div className="kicker" style={{ marginBottom: 8 }}>Demo accounts · password demo1234</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          {DEMO.map((d) => (
            <button key={d.email} onClick={() => setEmail(d.email)}
              style={{ textAlign: "left", background: "none", border: 0, padding: "5px 4px", cursor: "pointer", borderRadius: 6, color: "var(--ink)" }}>
              <span className="mono" style={{ fontSize: 12, color: "var(--accent)" }}>{d.email.split("@")[0]}</span>
              <span className="muted" style={{ fontSize: 12 }}> — {d.role}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
