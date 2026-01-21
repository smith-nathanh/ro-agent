"""Output formatting for evaluation results."""

import json
from pathlib import Path
from typing import Any

from .config import EvalMetrics, TaskResult


def write_results(
    results: list[TaskResult],
    metrics: EvalMetrics,
    output_dir: Path | str,
    prefix: str = "",
) -> tuple[Path, Path, Path]:
    """Write evaluation results in AgentBench format.

    Creates three files:
    - runs.jsonl: Per-task results (one JSON object per line)
    - overall.json: Aggregate metrics
    - summary.txt: Human-readable summary

    Args:
        results: List of task results
        metrics: Aggregate metrics
        output_dir: Directory to write files to
        prefix: Optional prefix for output filenames

    Returns:
        Tuple of (runs_path, overall_path, summary_path)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build filenames
    runs_filename = f"{prefix}runs.jsonl" if prefix else "runs.jsonl"
    overall_filename = f"{prefix}overall.json" if prefix else "overall.json"
    summary_filename = f"{prefix}summary.txt" if prefix else "summary.txt"

    runs_path = output_dir / runs_filename
    overall_path = output_dir / overall_filename
    summary_path = output_dir / summary_filename

    # Write runs.jsonl
    with open(runs_path, "w", encoding="utf-8") as f:
        for result in results:
            line = json.dumps(result.to_dict(), ensure_ascii=False)
            f.write(line + "\n")

    # Write overall.json
    with open(overall_path, "w", encoding="utf-8") as f:
        json.dump(metrics.to_dict(), f, indent=2, ensure_ascii=False)

    # Write summary.txt
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(print_summary(metrics))
        f.write("\n")

    return runs_path, overall_path, summary_path


def print_summary(metrics: EvalMetrics) -> str:
    """Format a summary of evaluation metrics for display.

    Args:
        metrics: Aggregate metrics

    Returns:
        Formatted summary string
    """
    lines = [
        "=" * 50,
        "Evaluation Results",
        "=" * 50,
        f"Total tasks:     {metrics.total}",
        f"Passed:          {metrics.passed}",
        f"Failed:          {metrics.failed}",
        f"Accuracy:        {metrics.accuracy:.2%}",
        "",
        "Status Breakdown:",
        f"  Completed:           {metrics.completed}",
        f"  Context limit:       {metrics.context_limit}",
        f"  Validation failed:   {metrics.validation_failed}",
        f"  Invalid action:      {metrics.invalid_action}",
        f"  Turn limit reached:  {metrics.task_limit_reached}",
        f"  Task error:          {metrics.task_error}",
        "",
        "History Length:",
        f"  Average: {metrics.average_history_length:.1f}",
        f"  Min:     {metrics.min_history_length}",
        f"  Max:     {metrics.max_history_length}",
        "=" * 50,
    ]

    return "\n".join(lines)


def load_results(runs_path: Path | str) -> list[dict[str, Any]]:
    """Load results from a runs.jsonl file.

    Args:
        runs_path: Path to runs.jsonl file

    Returns:
        List of result dictionaries
    """
    results = []
    with open(runs_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def load_overall(overall_path: Path | str) -> dict[str, Any]:
    """Load overall metrics from an overall.json file.

    Args:
        overall_path: Path to overall.json file

    Returns:
        Metrics dictionary
    """
    with open(overall_path, "r", encoding="utf-8") as f:
        return json.load(f)
