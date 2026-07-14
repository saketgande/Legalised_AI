"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, type TabularCell, type TabularDoc } from "../../lib/api";

const PRESETS = [
  "Limitation of liability cap",
  "Governing law",
  "Term length",
  "Mutual or one-way?",
  "Auto-renewal?",
  "Assignment permitted?",
];
const MAX_ROWS = 60, MAX_COLS = 12;
const key = (rid: string, q: string) => `${rid}::${q}`;

export default function Tabular() {
  const [docs, setDocs] = useState<TabularDoc[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [picking, setPicking] = useState(false);
  const [docSearch, setDocSearch] = useState("");
  const [columns, setColumns] = useState<string[]>([]);
  const [newCol, setNewCol] = useState("");
  const [running, setRunning] = useState(false);
  const [cells, setCells] = useState<Record<string, { value: string; section: string; url: string | null }>>({});
  const [filter, setFilter] = useState("");
  const [sort, setSort] = useState<{ q: string; dir: 1 | -1 } | null>(null);
  const runQs = useRef<string[]>([]);

  useEffect(() => { api.tabularDocuments().then(setDocs).catch(() => {}); }, []);

  const selectedDocs = useMemo(() => docs.filter((d) => selected.has(d.request_id)), [docs, selected]);
  const rows = useMemo(() => {
    let out = selectedDocs;
    const n = filter.trim().toLowerCase();
    if (n) out = out.filter((d) => d.ref.toLowerCase().includes(n) || d.counterparty.toLowerCase().includes(n));
    if (sort) {
      const val = (d: TabularDoc) => sort.q === "__doc__" ? `${d.ref} ${d.counterparty}` : (cells[key(d.request_id, sort.q)]?.value ?? "~");
      out = [...out].sort((a, b) => val(a).localeCompare(val(b)) * sort.dir);
    }
    return out;
  }, [selectedDocs, filter, sort, cells]);

  function addColumn(q: string) {
    const v = q.trim();
    if (!v || columns.includes(v) || columns.length >= MAX_COLS) return;
    setColumns((c) => [...c, v]);
    setNewCol("");
  }
  function toggleSort(q: string) {
    setSort((s) => s && s.q === q ? (s.dir === 1 ? { q, dir: -1 } : null) : { q, dir: 1 });
  }

  async function run() {
    const ids = [...selected].slice(0, MAX_ROWS);
    const qs = columns.slice(0, MAX_COLS);
    if (!ids.length || !qs.length || running) return;
    // clear the cells we're about to (re)compute
    setCells((prev) => {
      const c = { ...prev };
      ids.forEach((rid) => qs.forEach((q) => delete c[key(rid, q)]));
      return c;
    });
    setRunning(true);
    runQs.current = qs;
    try {
      await api.tabularRun(ids, qs, {
        onMeta: (_rows, questions) => { runQs.current = questions; },
        onCell: (c: TabularCell) => {
          const q = runQs.current[c.col];
          if (q === undefined) return;
          setCells((prev) => ({ ...prev, [key(c.request_id, q)]: { value: c.value, section: c.section, url: c.url } }));
        },
        onDone: () => setRunning(false),
      });
    } catch { /* leave filled cells; surfaced by empty cells */ } finally { setRunning(false); }
  }

  function exportCsv() {
    const esc = (s: string) => `"${(s || "").replace(/"/g, '""')}"`;
    const header = ["Document", "Counterparty", ...columns].map(esc).join(",");
    const lines = rows.map((d) =>
      [d.ref, d.counterparty, ...columns.map((q) => cells[key(d.request_id, q)]?.value ?? "")].map(esc).join(","));
    const blob = new Blob([[header, ...lines].join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `tabular-review-${rows.length}x${columns.length}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  }

  const cellCount = selectedDocs.length * columns.length;
  const canRun = selected.size > 0 && columns.length > 0 && !running;

  return (
    <div>
      <div className="page-head" style={{ marginBottom: 10 }}>
        <div className="page-head-row">
          <div>
            <p className="kicker">AI · document grid</p>
            <h1>Tabular Review</h1>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn sm" onClick={exportCsv} disabled={!rows.length || !columns.length}>Export CSV</button>
            <button className="btn primary sm" onClick={run} disabled={!canRun}>
              {running ? "Running…" : `Run ${cellCount || ""} ${cellCount ? "cells" : ""}`.trim() || "Run"}
            </button>
          </div>
        </div>
      </div>

      {/* toolbar */}
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
        <button className="btn sm" onClick={() => setPicking(true)}>+ Documents ({selected.size})</button>
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter rows…" style={{ width: 180 }} />
        <span style={{ flex: 1 }} />
        <span className="mono" style={{ fontSize: 11, color: "var(--faint)" }}>
          {selectedDocs.length} docs × {columns.length} questions = {cellCount} cells
          {selectedDocs.length > MAX_ROWS && <span style={{ color: "var(--warn)" }}> · first {MAX_ROWS} run</span>}
        </span>
      </div>

      {/* columns editor */}
      <div className="tab-cols">
        <span className="mono" style={{ fontSize: 10, color: "var(--faint)", textTransform: "uppercase", letterSpacing: "0.1em" }}>Columns</span>
        {columns.map((q) => (
          <span key={q} className="col-chip">
            {q}
            <button onClick={() => setColumns((c) => c.filter((x) => x !== q))} title="Remove column">×</button>
          </span>
        ))}
        {columns.length < MAX_COLS && (
          <input value={newCol} onChange={(e) => setNewCol(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") addColumn(newCol); }}
            placeholder="+ add a question…" style={{ width: 190, fontSize: 12.5 }} />
        )}
        {columns.length === 0 && (
          <span style={{ display: "inline-flex", gap: 5, flexWrap: "wrap" }}>
            {PRESETS.map((p) => <button key={p} className="preset-chip" onClick={() => addColumn(p)}>+ {p}</button>)}
          </span>
        )}
      </div>

      {/* grid */}
      {selected.size === 0 ? (
        <div className="card card-pad" style={{ textAlign: "center", padding: 44 }}>
          <div className="h-serif" style={{ fontSize: 22, marginBottom: 6 }}>Build a review grid</div>
          <p className="muted" style={{ fontSize: 13, marginBottom: 16 }}>Pick a set of documents, write a question per column, and every cell is an extracted answer linked to its source.</p>
          <button className="btn primary" onClick={() => setPicking(true)}>+ Add documents</button>
        </div>
      ) : (
        <div className="card" style={{ overflow: "auto", maxHeight: "calc(100vh - 280px)" }}>
          <table className="tab-grid">
            <thead>
              <tr>
                <th className="doc-col" onClick={() => toggleSort("__doc__")}>
                  Document ({rows.length}){sort?.q === "__doc__" && (sort.dir === 1 ? " ↑" : " ↓")}
                </th>
                {columns.map((q) => (
                  <th key={q} onClick={() => toggleSort(q)} title="Click to sort">
                    {q}{sort?.q === q && (sort.dir === 1 ? " ↑" : " ↓")}
                  </th>
                ))}
                {columns.length === 0 && <th style={{ color: "var(--faint)", fontWeight: 400 }}>Add a question column →</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.request_id}>
                  <td className="doc-col">
                    <Link href={d.url} className="mono" style={{ color: "var(--accent-ink)", fontSize: 12, fontWeight: 600, textDecoration: "none" }}>{d.ref}</Link>
                    <div style={{ fontSize: 12, color: "var(--ink)", marginTop: 1 }}>{d.counterparty}</div>
                    <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", textTransform: "uppercase" }}>{d.type}</div>
                  </td>
                  {columns.map((q) => {
                    const c = cells[key(d.request_id, q)];
                    const pending = running && !c;
                    return (
                      <td key={q}>
                        {pending ? <span className="cell-spin" />
                          : c ? (
                            <>
                              <div style={{ fontSize: 12.5, color: c.value === "Not addressed" || c.value === "No document" ? "var(--faint)" : "var(--ink)", lineHeight: 1.45 }}>{c.value}</div>
                              {c.section && c.url && (
                                <Link href={c.url} className="cell-src" title="Open the source clause">§{c.section} →</Link>
                              )}
                            </>
                          ) : <span style={{ color: "var(--faint)" }}>—</span>}
                      </td>
                    );
                  })}
                  {columns.length === 0 && <td style={{ color: "var(--faint)" }}>—</td>}
                </tr>
              ))}
              {rows.length === 0 && (
                <tr><td colSpan={columns.length + 1} className="muted" style={{ textAlign: "center", padding: 24 }}>No rows match this filter.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="mono" style={{ fontSize: 9.5, color: "var(--faint)", marginTop: 8 }}>
        Advisory only · each cell is an extraction grounded in that document's clauses · every run is sealed on the audit chain
      </div>

      {/* document picker */}
      {picking && (
        <div className="modal-scrim" onClick={() => setPicking(false)}>
          <div className="card card-pad" style={{ width: "min(560px, 94vw)", maxHeight: "80vh", display: "flex", flexDirection: "column" }} onClick={(e) => e.stopPropagation()}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <span className="kicker">Add documents · {selected.size} selected</span>
              <button className="btn sm ghost" onClick={() => setPicking(false)}>Done</button>
            </div>
            <input value={docSearch} onChange={(e) => setDocSearch(e.target.value)} placeholder="Search ref / counterparty…" style={{ marginBottom: 8 }} />
            <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
              <button className="linkish" onClick={() => setSelected(new Set(docs.map((d) => d.request_id)))}>Select all ({docs.length})</button>
              <button className="linkish" onClick={() => setSelected(new Set())}>Clear</button>
            </div>
            <div style={{ overflowY: "auto", flex: 1 }}>
              {docs.filter((d) => { const n = docSearch.trim().toLowerCase(); return !n || d.ref.toLowerCase().includes(n) || d.counterparty.toLowerCase().includes(n); }).map((d) => (
                <label key={d.request_id} className="pick-row">
                  <input type="checkbox" checked={selected.has(d.request_id)}
                    onChange={() => setSelected((s) => { const n = new Set(s); n.has(d.request_id) ? n.delete(d.request_id) : n.add(d.request_id); return n; })} />
                  <span className="mono" style={{ fontSize: 11, color: "var(--accent-ink)", width: 110 }}>{d.ref}</span>
                  <span style={{ fontSize: 12.5, color: "var(--ink)", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.counterparty}</span>
                  <span className="mono" style={{ fontSize: 9.5, color: "var(--faint)", textTransform: "uppercase" }}>{d.type}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
