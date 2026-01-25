"""Entry point for running ro-agent inside Harbor containers.

This module runs ro-agent with unrestricted eval-mode tools using the
capability profile system. The container provides sandboxing, so tool-level
restrictions are unnecessary.

Usage:
    python -m ro_agent.eval.harbor.runner "<instruction>" [working_dir]

Environment variables:
    RO_AGENT_MODEL      - Model to use (default: gpt-5-mini)
    RO_AGENT_BASE_URL   - API base URL (default: OpenAI)
    RO_AGENT_MAX_TURNS  - Max conversation turns (default: 50)
    OPENAI_API_KEY      - API key (required)
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from ro_agent.capabilities import CapabilityProfile
from ro_agent.capabilities.factory import ToolFactory
from ro_agent.client.model import ModelClient
from ro_agent.core.agent import Agent
from ro_agent.core.session import Session

# Load .env file - try multiple locations
# 1. Current directory
# 2. ro-agent package root (where this file lives, up 4 levels)
# 3. /ro-agent (Harbor container mount point)
_pkg_root = Path(__file__).parent.parent.parent.parent
for env_path in [Path.cwd() / ".env", _pkg_root / ".env", Path("/ro-agent/.env")]:
    if env_path.exists():
        load_dotenv(env_path)
        break

SYSTEM_PROMPT = """\
You are an AI agent that completes tasks in a Linux environment.

Available tools:
- bash: Execute any shell command
- write: Create or overwrite a file
- edit: Make surgical edits to existing files
- read: Read file contents
- grep: Search for patterns in files (using ripgrep)
- glob: Find files by name/pattern
- list: List directory contents

Guidelines:
- Execute commands to investigate and solve problems
- Use edit for surgical changes to existing files
- Use write to create new files or fully replace content
- Read files before editing them to understand the current state
- Be precise and efficient
- If a task requires installing packages, use pip/apt as needed
- For build tasks, use appropriate build tools (make, cmake, cargo, etc.)
"""


async def auto_approve(tool_name: str, tool_args: dict) -> bool:
    """Auto-approve all tool calls in eval mode."""
    return True


async def run_task(instruction: str, working_dir: str = "/app") -> None:
    """Run ro-agent on a TerminalBench task.

    Args:
        instruction: The task description/instruction.
        working_dir: Working directory for shell commands (default: /app).
    """
    session = Session(system_prompt=SYSTEM_PROMPT)

    # Use eval profile - unrestricted, no approval required
    profile = CapabilityProfile.eval(working_dir=working_dir)
    factory = ToolFactory(profile)
    registry = factory.create_registry(working_dir=working_dir)

    # Create client from environment
    model = os.environ.get("RO_AGENT_MODEL", "gpt-5-mini")
    base_url = os.environ.get("RO_AGENT_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY")

    client = ModelClient(
        model=model,
        base_url=base_url,
        api_key=api_key,
    )

    # Create agent with auto-approval (container is sandbox)
    agent = Agent(
        session=session,
        registry=registry,
        client=client,
        approval_callback=auto_approve,
        auto_compact=True,
    )

    # Run until completion or max turns
    max_turns = int(os.environ.get("RO_AGENT_MAX_TURNS", "50"))
    current_input = instruction

    for turn in range(max_turns):
        has_tool_calls = False

        async for event in agent.run_turn(current_input):
            if event.type == "text" and event.content:
                print(event.content, end="", flush=True)
            elif event.type == "tool_start":
                # Log tool invocations for debugging
                print(f"\n[Tool: {event.tool_name}]", file=sys.stderr)
            elif event.type == "tool_end":
                has_tool_calls = True
                # Optionally log tool results
                if os.environ.get("RO_AGENT_DEBUG"):
                    result_preview = (
                        event.tool_result[:200] + "..."
                        if event.tool_result and len(event.tool_result) > 200
                        else event.tool_result
                    )
                    print(f"[Result: {result_preview}]", file=sys.stderr)
            elif event.type == "error":
                print(f"\nError: {event.content}", file=sys.stderr)
            elif event.type == "turn_complete":
                # Log usage stats
                if event.usage:
                    print(
                        f"\n[Tokens: in={event.usage.get('total_input_tokens', 0)}, "
                        f"out={event.usage.get('total_output_tokens', 0)}]",
                        file=sys.stderr,
                    )

        # If no tool calls were made, agent is done
        if not has_tool_calls:
            break

        # Continue with empty prompt (agent has context)
        current_input = "Continue with the task."

    print()  # Final newline


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print(
            "Usage: python -m ro_agent.eval.harbor.runner '<instruction>' [working_dir]",
            file=sys.stderr,
        )
        sys.exit(1)

    instruction = sys.argv[1]
    working_dir = sys.argv[2] if len(sys.argv) > 2 else "/app"

    asyncio.run(run_task(instruction, working_dir))


if __name__ == "__main__":
    main()
