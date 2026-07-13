import type { TimelineEvent } from "../../lib/api";

const ACTION_LABELS: Record<string, string> = {
  "request.created": "Request filed",
  "request.classified": "Classified the request",
  "request.routed": "Routed",
  "document.generated": "Assembled the NDA from the playbook",
  "request.auto_approved": "Auto-approved — within policy",
  "review.requested": "Sent for review",
  "ladder.step.approved": "Approved a step",
  "request.approved": "All approvals cleared",
  "request.sent": "Sent for signature",
  "request.executed": "Countersigned",
  "request.filed": "Filed — renewal tracked",
};

export function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <ul className="timeline">
      {events.map((e) => (
        <li key={e.chain_position}>
          <span className="pos">#{e.chain_position}</span>
          <span className="who">
            <span className={`badge-actor ${e.actor_type}`}>{e.actor_label}</span>
          </span>
          <span>
            <span className="act">{ACTION_LABELS[e.action] ?? e.action}</span>
            {typeof e.metadata?.lane === "string" && (
              <span className="muted"> · {e.metadata.lane as string}</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
