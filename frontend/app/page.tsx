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

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginTop: 34 }}>
        <Link href="/new" className="card" style={{ padding: 22, display: "block" }}>
          <div style={{ fontSize: 24 }}>📝</div>
          <div className="h-serif" style={{ fontSize: 19, margin: "8px 0 4px" }}>I need an NDA</div>
          <p className="muted" style={{ fontSize: 13.5, margin: 0 }}>
            The requester&rsquo;s view. Fill a short form; track it like a package.
          </p>
        </Link>
        <Link href="/inbox" className="card" style={{ padding: 22, display: "block" }}>
          <div style={{ fontSize: 24 }}>⚖️</div>
          <div className="h-serif" style={{ fontSize: 19, margin: "8px 0 4px" }}>Legal inbox</div>
          <p className="muted" style={{ fontSize: 13.5, margin: 0 }}>
            The reviewer&rsquo;s cockpit. Triage, approve deviations, send.
          </p>
        </Link>
      </div>

      <p className="muted" style={{ fontSize: 12.5, marginTop: 28 }}>
        Walking skeleton · outbound NDA end-to-end. Inbound third-party redlining is the next slice.
      </p>
    </div>
  );
}
