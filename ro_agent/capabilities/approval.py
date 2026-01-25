"""Approval policy for tool execution.

Provides granular control over which tool invocations require user approval,
including pattern-based detection of dangerous commands.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from . import ApprovalMode, CapabilityProfile, DEFAULT_DANGEROUS_PATTERNS


@dataclass
class ApprovalPolicy:
    """Policy for determining when tool execution requires user approval.

    Supports multiple modes:
    - NONE: Never require approval (sandboxed environments)
    - ALL: Always require approval
    - DANGEROUS: Require approval for predefined dangerous tools
    - GRANULAR: Configurable per-tool approval with pattern matching
    """

    profile: CapabilityProfile
    _pattern_cache: dict[str, re.Pattern[str]] = field(default_factory=dict)

    def requires_approval(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None
    ) -> tuple[bool, str | None]:
        """Check if a tool invocation requires approval.

        Args:
            tool_name: Name of the tool being invoked
            arguments: Tool arguments (for pattern checking)

        Returns:
            (requires_approval, reason) - reason is None if no approval needed
        """
        # Check profile-level approval for the tool
        if self.profile.requires_tool_approval(tool_name):
            return True, f"Tool '{tool_name}' requires approval"

        # Even if tool doesn't require approval, check for dangerous patterns in arguments
        if arguments:
            dangerous = self._check_dangerous_patterns(arguments)
            if dangerous:
                return True, f"Command contains dangerous pattern: {dangerous}"

        return False, None

    def _check_dangerous_patterns(self, arguments: dict[str, Any]) -> str | None:
        """Check if arguments contain any dangerous patterns.

        Returns the matched pattern if found, None otherwise.
        """
        # Convert all argument values to strings for checking
        text_to_check = " ".join(
            str(v) for v in arguments.values() if v is not None
        )

        for pattern in self.profile.dangerous_patterns:
            if self._matches_pattern(pattern, text_to_check):
                return pattern

        return None

    def _matches_pattern(self, pattern: str, text: str) -> bool:
        """Check if text matches a dangerous pattern.

        Supports both literal matching and regex patterns (prefixed with 'regex:').
        """
        if pattern.startswith("regex:"):
            regex_pattern = pattern[6:]
            if regex_pattern not in self._pattern_cache:
                try:
                    self._pattern_cache[regex_pattern] = re.compile(regex_pattern, re.IGNORECASE)
                except re.error:
                    # Invalid regex, fall back to literal match
                    return pattern[6:].lower() in text.lower()
            return bool(self._pattern_cache[regex_pattern].search(text))
        else:
            # Literal pattern matching (case-insensitive)
            return pattern.lower() in text.lower()


def create_approval_policy(profile: CapabilityProfile) -> ApprovalPolicy:
    """Create an approval policy from a capability profile."""
    return ApprovalPolicy(profile=profile)


# Predefined approval policies for common scenarios
class ApprovalPolicies:
    """Factory for common approval policy configurations."""

    @staticmethod
    def none() -> ApprovalPolicy:
        """No approval required (for sandboxed containers)."""
        return ApprovalPolicy(profile=CapabilityProfile.eval())

    @staticmethod
    def dangerous_only() -> ApprovalPolicy:
        """Approve only dangerous tools."""
        return ApprovalPolicy(profile=CapabilityProfile.readonly())

    @staticmethod
    def all_tools() -> ApprovalPolicy:
        """Approve all tool invocations."""
        profile = CapabilityProfile.readonly()
        profile = CapabilityProfile(
            name="strict",
            shell=profile.shell,
            file_write=profile.file_write,
            database=profile.database,
            approval=ApprovalMode.ALL,
        )
        return ApprovalPolicy(profile=profile)

    @staticmethod
    def custom(
        required_tools: set[str] | None = None,
        dangerous_patterns: tuple[str, ...] | None = None,
    ) -> ApprovalPolicy:
        """Create a custom approval policy."""
        profile = CapabilityProfile(
            name="custom",
            approval=ApprovalMode.GRANULAR,
            approval_required_tools=frozenset(required_tools or set()),
            dangerous_patterns=dangerous_patterns or DEFAULT_DANGEROUS_PATTERNS,
        )
        return ApprovalPolicy(profile=profile)
