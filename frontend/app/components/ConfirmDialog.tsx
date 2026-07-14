"use client";
import { useEffect, useRef, useState } from "react";

/* Paranoia confirmation for irreversible actions: the user re-types a phrase
   before the destructive button arms. Reads as respect for gravity, not friction. */
export function ConfirmDialog({
  open, title, body, phrase, actionLabel, danger = true, busy = false, onConfirm, onClose,
}: {
  open: boolean;
  title: string;
  body: React.ReactNode;
  phrase: string;           // what the user must type, verbatim
  actionLabel: string;      // e.g. "Send to counterparty"
  danger?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTyped("");
      setTimeout(() => inputRef.current?.focus(), 30);
    }
  }, [open]);
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;
  const armed = typed.trim() === phrase;

  return (
    <div className="cp-overlay" onClick={onClose}>
      <div className="card confirm-panel" onClick={(e) => e.stopPropagation()}>
        <div style={{ fontWeight: 660, fontSize: 15, marginBottom: 8 }}>{title}</div>
        <div className="muted" style={{ fontSize: 13, lineHeight: 1.55, marginBottom: 14 }}>{body}</div>
        <div className="field" style={{ marginBottom: 12 }}>
          <label>Type <b className="mono" style={{ userSelect: "all" }}>{phrase}</b> to confirm</label>
          <input ref={inputRef} value={typed} onChange={(e) => setTyped(e.target.value)}
            placeholder={phrase} autoComplete="off" spellCheck={false} />
        </div>
        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className={`btn ${danger ? "danger" : "primary"}`} disabled={!armed || busy} onClick={onConfirm}>
            {busy ? "Working…" : actionLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
