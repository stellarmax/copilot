"""Manual check: run chat questions against the AI provider saved in AI settings.

This calls the real provider API and may cost money, so it is not part of the unit tests.
By default it runs one question; pass questions as arguments, or --all for the three
Overview examples.

    .venv\\Scripts\\python.exe -m backend.live_check_agent
    .venv\\Scripts\\python.exe -m backend.live_check_agent "How did assembly perform last week?"
    .venv\\Scripts\\python.exe -m backend.live_check_agent --all
"""

from __future__ import annotations

import asyncio
import sys

from backend.dev import DATA_DIR  # also loads the local encryption key the same way the dev server does
from backend.app.agent.service import AgentService, AgentTurnError
from backend.app.agent.store import AgentStore
from backend.copilot import BACKEND_DIR, DEFAULT_CONFIG_PATH, CopilotCore

EXAMPLES = [
    "Which orders need attention?",
    "How did assembly perform last week?",
    "Can we take 500 hoodies by April 30?",
]


async def main(questions: list[str]) -> int:
    db_path = BACKEND_DIR / ".frontend-demo.sqlite3"
    store = AgentStore(db_path)
    core = CopilotCore(DATA_DIR, db_path, DEFAULT_CONFIG_PATH)
    settings = store.get_ai_settings()
    print(f"Provider: {settings['provider']} / {settings['model']}  ·  data: {DATA_DIR}\n")
    failures = 0
    try:
        for question in questions:
            conversation = store.create_conversation("Live check")
            try:
                result = await AgentService(store, core).run_turn(conversation["conversation_id"], question)
            except AgentTurnError as exc:
                print(f"Q: {question}\n   ERROR: {exc}\n")
                failures += 1
                continue
            finally:
                store.delete_conversation(conversation["conversation_id"])
            print(f"Q: {question}")
            for event in result["tool_events"]:
                print(f"   tool: {event['tool_name']} [{event['result_status']}] {event['summary']}")
            print(f"   status: {result['status']}")
            print(f"A: {result['assistant_message']}\n")
            if result["status"] != "OK":
                failures += 1
    finally:
        core.close()
        store.close()
    return 1 if failures else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    selected = EXAMPLES if args == ["--all"] else (args or EXAMPLES[:1])
    sys.exit(asyncio.run(main(selected)))
