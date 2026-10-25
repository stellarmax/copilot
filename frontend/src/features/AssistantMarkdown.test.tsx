import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { AssistantMarkdown, stripClaimReferences, ToolResultCard } from "./ChatPage";

afterEach(cleanup);

describe("ToolResultCard", () => {
  it("shows only the brief-level claim, not one per finding", () => {
    const { container } = render(
      <ToolResultCard
        event={{
          tool_name: "discover_operational_issues",
          result_status: "OK",
          summary: "Brief contains 2 prioritized finding(s).",
          claim_ids: ["CLM-A", "CLM-BRIEF", "CLM-B"],
          data: {
            findings: [
              { finding_id: "f1", severity: "CRITICAL", summary: "2 high-risk orders", claim_id: "CLM-A" },
              { finding_id: "f2", severity: "INFO", summary: "Assembly output dropped", claim_id: "CLM-B" },
            ],
          },
        } as any}
        onTrace={() => {}}
        onClarify={() => {}}
      />,
    );

    const titles = (selector: string) => [...container.querySelectorAll(`${selector} .claim-badge`)].map((badge) => badge.getAttribute("title"));
    expect(titles(".chat-finding-line")).toEqual([]);
    expect(titles(".chat-claim-list")).toEqual(["Open evidence CLM-BRIEF"]);
  });
});

describe("AssistantMarkdown", () => {
  it("renders bold text, lists and tables instead of raw Markdown", () => {
    const { container } = render(
      <AssistantMarkdown
        content={"**Critical:** two orders\n\n- ORD-101\n- ORD-102\n\n| Stage | Pieces |\n|---|---|\n| ASSEMBLY | 400 |"}
      />,
    );

    expect(container.querySelector("strong")?.textContent).toBe("Critical:");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("td")?.textContent).toBe("ASSEMBLY");
    expect(container.textContent).not.toContain("**");
  });

  it("does not render raw HTML from the model", () => {
    const { container } = render(<AssistantMarkdown content={'<img src="x" onerror="alert(1)"> hi'} />);

    expect(container.querySelector("img")).toBeNull();
  });

  it("removes per-item evidence lines and inline claim IDs from the reply text", () => {
    const reply = [
      "1. **Critical (priority 90): TrendCart has 2 high-risk orders.**",
      "   - Recommended next step: review the affected orders together with the account owner.",
      "   - Evidence: CLM-20260401-DISC-001-28a23932",
      "",
      "2. **Info: Assembly output dropped** (priority 47). [CLM-20260401-NORM-002-5511d0a9]",
      "   - **Evidence:** `CLM-20260401-NORM-002-5511d0a9`",
    ].join("\n");

    const { container } = render(<AssistantMarkdown content={reply} />);

    expect(container.textContent).not.toMatch(/CLM-|Evidence/);
    expect(container.querySelectorAll("li")).toHaveLength(3);
    expect(container.textContent).toContain("Assembly output dropped (priority 47).");
    expect(container.querySelector("button")).toBeNull();
  });

  it("keeps ordinary text that mentions evidence without a claim ID", () => {
    expect(stripClaimReferences("Evidence: the brief is complete.")).toBe("Evidence: the brief is complete.");
  });
});
