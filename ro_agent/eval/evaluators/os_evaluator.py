"""OS Interaction evaluation logic."""

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..tasks.os_interaction import EvaluationConfig


class OSEvaluator:
    """Evaluator for OS Interaction tasks.

    Supports two evaluation modes:
    - match: Direct string comparison
    - check: Run check scripts (integer-match, string-match, containing, etc.)
    """

    def __init__(self, scripts_dir: Path | str | None = None) -> None:
        """Initialize the OS evaluator.

        Args:
            scripts_dir: Directory containing check scripts
        """
        self._scripts_dir = Path(scripts_dir) if scripts_dir else None

    async def evaluate(
        self,
        answer: str | None,
        eval_config: "EvaluationConfig",
        container=None,  # Optional: EvalContainer for running scripts in container
    ) -> bool:
        """Evaluate an agent's answer.

        Args:
            answer: The agent's submitted answer
            eval_config: Evaluation configuration from the task
            container: Optional container for running check scripts

        Returns:
            True if the answer is correct
        """
        if answer is None:
            return False

        if eval_config.eval_type == "match":
            return self._evaluate_match(answer, eval_config.match_answer)
        elif eval_config.eval_type == "check":
            return await self._evaluate_check(answer, eval_config, container)
        else:
            return False

    def _evaluate_match(self, answer: str, expected: str | None) -> bool:
        """Evaluate using direct string match."""
        if expected is None:
            return False

        # Normalize newlines and whitespace
        answer_norm = self._normalize_string(answer)
        expected_norm = self._normalize_string(expected)

        return answer_norm == expected_norm

    def _normalize_string(self, s: str) -> str:
        """Normalize a string for comparison."""
        # Normalize newlines
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        # Strip whitespace
        return s.strip()

    async def _evaluate_check(
        self,
        answer: str,
        eval_config: "EvaluationConfig",
        container=None,
    ) -> bool:
        """Evaluate using check scripts."""
        if not eval_config.check_scripts:
            return False

        # If there's an example script, run it first to get expected value
        expected_value = None
        if eval_config.example_script and container:
            expected_value = await self._run_example_script(
                eval_config.example_script, container
            )

        # Run each check script
        for check_script in eval_config.check_scripts:
            if not check_script.file:
                continue

            result = await self._run_check_script(
                answer,
                expected_value or "",
                check_script.file,
                container,
            )

            if not result:
                return False

        return True

    async def _run_example_script(
        self, example_config: dict, container
    ) -> str | None:
        """Run an example script to get expected value."""
        if not example_config:
            return None

        script_file = example_config.get("file")
        if not script_file:
            return None

        try:
            # Run the script in the container to get expected output
            exit_code, stdout, stderr = await container.execute(
                f"python3 {script_file}",
                timeout=30,
            )
            if exit_code == 0:
                return stdout.strip()
        except Exception:
            pass

        return None

    async def _run_check_script(
        self,
        answer: str,
        expected: str,
        script_path: str,
        container=None,
    ) -> bool:
        """Run a single check script.

        Check scripts take two arguments: answer and expected
        Exit code 0 = pass, non-zero = fail
        """
        # Determine the check script type from filename
        script_name = Path(script_path).name

        # Try to run inline if we have the check scripts locally
        if self._scripts_dir:
            local_script = self._scripts_dir / script_path
            if local_script.exists():
                return await self._run_local_check(answer, expected, local_script)

        # Run built-in checks based on script name
        return self._run_builtin_check(answer, expected, script_name)

    async def _run_local_check(
        self, answer: str, expected: str, script_path: Path
    ) -> bool:
        """Run a local check script."""
        try:
            result = subprocess.run(
                ["python3", str(script_path), answer, expected],
                capture_output=True,
                timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _run_builtin_check(self, answer: str, expected: str, script_name: str) -> bool:
        """Run built-in check implementations."""
        # Normalize inputs
        answer = self._normalize_string(answer)
        expected = self._normalize_string(expected)

        if script_name == "integer-match.py":
            try:
                return int(answer) == int(expected)
            except ValueError:
                return False

        elif script_name == "string-match.py":
            return answer == expected

        elif script_name == "containing.py":
            # Check if expected is contained in answer
            return expected in answer

        elif script_name == "in.py":
            # Check if answer is contained in expected
            return answer in expected

        elif script_name == "size-match.py":
            return self._size_match(answer, expected)

        else:
            # Default to string match
            return answer == expected

    def _size_match(self, answer: str, expected: str) -> bool:
        """Compare file sizes with unit conversion."""
        units = {
            "B": 1,
            "Byte": 1,
            "K": 1024,
            "KB": 1024,
            "M": 1024 * 1024,
            "MB": 1024 * 1024,
            "G": 1024 * 1024 * 1024,
            "GB": 1024 * 1024 * 1024,
            "T": 1024**4,
            "TB": 1024**4,
            "P": 1024**5,
            "PB": 1024**5,
        }

        def parse_size(s: str) -> int:
            s = s.strip()
            for unit, multiplier in sorted(units.items(), key=lambda x: -len(x[0])):
                if s.endswith(unit):
                    try:
                        return int(s[: -len(unit)]) * multiplier
                    except ValueError:
                        return -1
            try:
                return int(s)
            except ValueError:
                return -1

        return parse_size(answer) == parse_size(expected)
