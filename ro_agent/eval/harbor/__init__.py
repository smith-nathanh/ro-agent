"""Harbor/TerminalBench integration for ro-agent.

This module provides the runner for executing ro-agent inside Harbor's
sandboxed container environments for TerminalBench evaluation.

Usage:
    # From within a Harbor container:
    python -m ro_agent.eval.harbor.runner "task instruction here"

    # Or via Harbor job config:
    # agents:
    #   - import_path: ro_agent.eval.harbor.agent:RoAgent
"""

# Re-export handlers for convenience
from ro_agent.tools.handlers import BashHandler, WriteHandler, EditHandler

__all__ = [
    "BashHandler",
    "WriteHandler",
    "EditHandler",
]
