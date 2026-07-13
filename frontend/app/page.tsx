import Link from "next/link";

export default function Home() {
  return (
    <div className="container narrow">
      <p className="kicker">Legal front door + CLM</p>
      <h1 className="h-serif" style={{ fontSize: 38, lineHeight: 1.1, margin: "10px 0 12px" }}>
        Request to signature, without the back-and-forth.
      </h1>
      <p className="muted" style={{ fontSize: 17, maxWidth: "58ch" }}>
        Anyone in the business asks for an NDA. Frontdoor classifies it, drafts it from the
        company&rsquo;s approved playbook, routes only the risky terms to a lawyer, and files the
        signed copy — every step on a tamper-evident audit chain.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16, marginTop: 34 }}>
        <Link href="/new" className="card" style={{ padding: 22, display: "block" }}>
          <div style={{ fontSize: 24 }}>📝</div>
          <div className="h-serif" style={{ fontSize: 18, margin: "8px 0 4px" }}>I need an NDA</div>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>
            Requester view. Fill a short form; track it like a package.
          </p>
        </Link>
        <Link href="/inbound" className="card" style={{ padding: 22, display: "block" }}>
          <div style={{ fontSize: 24 }}>🔍</div>
          <div className="h-serif" style={{ fontSize: 18, margin: "8px 0 4px" }}>Review their paper</div>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>
            Paste a counterparty NDA; the engine redlines it against your playbook.
          </p>
        </Link>
        <Link href="/inbox" className="card" style={{ padding: 22, display: "block" }}>
          <div style={{ fontSize: 24 }}>⚖️</div>
          <div className="h-serif" style={{ fontSize: 18, margin: "8px 0 4px" }}>Legal inbox</div>
          <p className="muted" style={{ fontSize: 13, margin: 0 }}>
            Reviewer cockpit. Triage, approve deviations, send.
          </p>
        </Link>
      </div>

      <p className="muted" style={{ fontSize: 12.5, marginTop: 28 }}>
        Outbound NDA generation + inbound third-party redline review, end-to-end, on a tamper-evident audit chain.
      </p>
    </div>
  );
}
