"""Harbor/TerminalBench integration for ro-agent.

This module provides tools and wrappers for running ro-agent inside
Harbor's sandboxed container environments for TerminalBench evaluation.

Usage:
    # From within a Harbor container:
    python -m ro_agent.harbor.runner "task instruction here"

    # Or via Harbor job config:
    # agents:
    #   - import_path: ro_agent.harbor.agent:RoAgent

The harbor tools (BashHandler, WriteHandler, EditHandler) are now unified
with the main tools module. Use the capability profile system to configure
unrestricted mode:

    from ro_agent.capabilities import CapabilityProfile
    from ro_agent.capabilities.factory import ToolFactory

    profile = CapabilityProfile.eval()
    factory = ToolFactory(profile)
    registry = factory.create_registry()
"""

# Re-export handlers for backward compatibility
# These are now aliases pointing to the unified handlers with appropriate modes
from ro_agent.tools.handlers import BashHandler, WriteHandler, EditHandler

# Backward compatibility aliases
WriteFileHandler = WriteHandler
EditFileHandler = EditHandler

__all__ = [
    "BashHandler",
    "WriteHandler",
    "EditHandler",
    # Backward compatibility
    "WriteFileHandler",
    "EditFileHandler",
]
