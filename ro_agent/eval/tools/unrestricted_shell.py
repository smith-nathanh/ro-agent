"""Unrestricted shell handler for evaluation tasks.

Unlike the allowlisted ShellHandler, this handler allows any command
for evaluation purposes.
"""

import asyncio
from typing import Any

from ro_agent.tools.base import ToolHandler, ToolInvocation, ToolOutput


DEFAULT_TIMEOUT = 120  # seconds


class UnrestrictedShellHandler(ToolHandler):
    """Shell handler without command restrictions.

    Used for OS interaction evaluation where the agent needs full
    shell access to complete tasks.
    """

    def __init__(
        self,
        working_dir: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        """Initialize the unrestricted shell handler.

        Args:
            working_dir: Working directory for commands
            timeout: Command timeout in seconds
        """
        self._working_dir = working_dir
        self._timeout = timeout

    @property
    def name(self) -> str:
        return "bash_action"

    @property
    def description(self) -> str:
        return (
            "Execute a shell command in the Linux environment. "
            "You can run any command to investigate the system, install packages, "
            "manipulate files, or perform any shell operation needed to complete the task."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
            },
            "required": ["command"],
        }

    @property
    def requires_approval(self) -> bool:
        return False  # No approval needed for eval tasks

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        """Execute the shell command."""
        command = invocation.arguments.get("command", "")

        if not command:
            return ToolOutput(content="No command provided", success=False)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return ToolOutput(
                    content=f"Command timed out after {self._timeout} seconds",
                    success=False,
                    metadata={"timed_out": True},
                )

            exit_code = process.returncode
            stdout_str = stdout.decode("utf-8", errors="replace")
            stderr_str = stderr.decode("utf-8", errors="replace")

            # Combine output
            output_parts = []
            if stdout_str:
                output_parts.append(stdout_str)
            if stderr_str:
                output_parts.append(f"[stderr]\n{stderr_str}")

            content = "\n".join(output_parts) if output_parts else "(no output)"

            return ToolOutput(
                content=content,
                success=exit_code == 0,
                metadata={
                    "exit_code": exit_code,
                    "command": command,
                },
            )

        except Exception as e:
            return ToolOutput(
                content=f"Error executing command: {e}",
                success=False,
            )
