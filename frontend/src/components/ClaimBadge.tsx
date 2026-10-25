import { ArrowUpRight } from "lucide-react";

interface ClaimBadgeProps {
  claimId: string;
  onClick: (claimId: string) => void;
}

export function ClaimBadge({ claimId, onClick }: ClaimBadgeProps) {
  return (
    <button className="claim-badge" onClick={() => onClick(claimId)} title={`Open evidence ${claimId}`}>
      Evidence <ArrowUpRight size={13} aria-hidden="true" />
    </button>
  );
}