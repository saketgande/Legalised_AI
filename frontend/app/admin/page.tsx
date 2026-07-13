"use client";
import { useEffect, useState } from "react";
import { api, type AuthUser } from "../../lib/api";
import { useAuth } from "../../lib/auth";

const ROLES = ["admin", "gc", "vp_legal", "attorney", "paralegal", "legal_ops", "requester", "viewer"];

export default function AdminPage() {
  const { has } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = () => api.listUsers().then(setUsers).catch((e) => setErr(String(e)));
  useEffect(() => { load(); }, []);

  async function changeRole(id: string, role: string) {
    setErr(null);
    try { await api.changeUserRole(id, role); await load(); }
    catch (e) { setErr(String(e).replace(/^Error:\s*/, "")); await load(); }
  }

  if (!has("admin:manage_users")) return <div className="container muted">Admins only.</div>;

  return (
    <div className="container">
      <p className="kicker">Admin</p>
      <h1 className="h-serif" style={{ fontSize: 26, margin: "4px 0 18px" }}>Users &amp; roles</h1>
      <p className="muted" style={{ fontSize: 13.5, marginBottom: 16, maxWidth: "70ch" }}>
        A user&rsquo;s role sets both what they can do and which deviations they can approve. Role
        changes are chain-sealed in the audit log; the last admin can&rsquo;t be demoted.
      </p>
      {err && <div className="notice warn" style={{ marginBottom: 14 }}>{err}</div>}

      <div className="card" style={{ overflow: "hidden" }}>
        <div style={{ overflowX: "auto" }}>
          <table className="inbox">
            <thead>
              <tr><th>Name</th><th>Email</th><th>Role</th><th>Rank</th><th>Status</th></tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="cp">{u.name}</td>
                  <td className="ref">{u.email}</td>
                  <td>
                    <select value={u.role} onChange={(e) => changeRole(u.id, e.target.value)}
                      style={{ fontFamily: "inherit", fontSize: 13, padding: "5px 8px", borderRadius: 7, border: "1px solid var(--hairline)", background: "var(--surface)", color: "var(--ink)" }}>
                      {ROLES.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}
                    </select>
                  </td>
                  <td className="mono muted">{u.rank}</td>
                  <td>{u.suspended ? <span className="pill escalated">suspended</span> : <span className="pill auto">active</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
