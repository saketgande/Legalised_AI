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
    <div>
      <div className="page-head">
        <p className="kicker">Administration</p>
        <h1>Users &amp; roles</h1>
        <p className="sub">
          A user&rsquo;s role sets both what they can do and which deviations they can approve. Role
          changes are chain-sealed in the audit log; the last admin can&rsquo;t be demoted.
        </p>
      </div>
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
                      style={{ fontSize: 13, padding: "6px 30px 6px 10px", width: "auto", minWidth: 150 }}>
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
