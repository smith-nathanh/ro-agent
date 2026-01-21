"""CLI for running AgentBench evaluations."""

import asyncio
import os
from pathlib import Path
from typing import Annotated, Optional

from dotenv import load_dotenv

# Load .env before anything else so env vars are available for defaults
load_dotenv()


def _default_output_dir(model: str, task_type: str) -> Path:
    """Get default output directory based on model name and task type."""
    # Sanitize model name for use as directory (replace / with -)
    safe_model = model.replace("/", "-")
    return Path("results") / f"{safe_model}-{task_type}"

import typer  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn  # noqa: E402

from .config import EvalConfig  # noqa: E402
from .output import print_summary, write_results  # noqa: E402
from .runner import EvalRunner  # noqa: E402
from .tasks.dbbench import load_dbbench_tasks  # noqa: E402
from .tasks.os_interaction import load_os_tasks, load_os_benchmark  # noqa: E402

console = Console()

app = typer.Typer(
    name="ro-eval",
    help="Run AgentBench evaluations through ro-agent.",
    add_completion=False,
)


@app.command()
def dbbench(
    data_file: Annotated[
        str,
        typer.Argument(help="Path to DBBench data file (standard.jsonl)"),
    ],
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Model to use"),
    ] = os.getenv("OPENAI_MODEL", "gpt-4o"),
    base_url: Annotated[
        Optional[str],
        typer.Option("--base-url", help="API base URL for OpenAI-compatible endpoints"),
    ] = os.getenv("OPENAI_BASE_URL"),
    max_turns: Annotated[
        int,
        typer.Option("--max-turns", help="Maximum turns per task"),
    ] = 20,
    parallel: Annotated[
        int,
        typer.Option("--parallel", "-p", help="Number of parallel tasks"),
    ] = 1,
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Output directory (default: results/<model>)"),
    ] = None,
    system_prompt: Annotated[
        Optional[str],
        typer.Option("--system-prompt", help="Path to custom system prompt file"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", "-n", help="Limit number of tasks to run"),
    ] = None,
    offset: Annotated[
        int,
        typer.Option("--offset", help="Skip first N tasks"),
    ] = 0,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
) -> None:
    """Run DBBench evaluation tasks."""
    # Load tasks
    console.print(f"Loading tasks from {data_file}...")
    tasks = load_dbbench_tasks(data_file)
    console.print(f"Loaded {len(tasks)} tasks")

    # Apply offset and limit
    if offset > 0:
        tasks = tasks[offset:]
    if limit is not None:
        tasks = tasks[:limit]

    console.print(f"Running {len(tasks)} tasks (offset={offset}, limit={limit})")

    # Set default output directory if not specified
    if output is None:
        output_path = _default_output_dir(model, "dbbench")
    else:
        output_path = Path(output)

    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    console.print(f"Results will be saved to: {output_path}")

    # Create config
    config = EvalConfig(
        model=model,
        base_url=base_url,
        max_turns=max_turns,
        parallel=parallel,
        output_dir=str(output_path),
        system_prompt_file=system_prompt,
        verbose=verbose,
    )

    # Create runner
    runner = EvalRunner(config)

    # Run with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Running DBBench...", total=len(tasks))

        def update_progress(completed: int, total: int) -> None:
            progress.update(task_id, completed=completed)

        # Run evaluation
        results, metrics = asyncio.run(
            runner.run_dbbench_tasks(tasks, progress_callback=update_progress)
        )

    # Print summary
    console.print()
    console.print(print_summary(metrics))

    # Write results
    runs_path, overall_path, summary_path = write_results(results, metrics, str(output_path))
    console.print("\nResults written to:")
    console.print(f"  {runs_path}")
    console.print(f"  {overall_path}")
    console.print(f"  {summary_path}")


@app.command()
def os_interaction(
    data_path: Annotated[
        str,
        typer.Argument(help="Path to JSON file or os_interaction directory for full benchmark"),
    ],
    scripts: Annotated[
        Optional[str],
        typer.Option("--scripts", "-s", help="Path to check scripts directory (for single file mode)"),
    ] = None,
    model: Annotated[
        str,
        typer.Option("--model", "-m", help="Model to use"),
    ] = os.getenv("OPENAI_MODEL", "gpt-4o"),
    base_url: Annotated[
        Optional[str],
        typer.Option("--base-url", help="API base URL for OpenAI-compatible endpoints"),
    ] = os.getenv("OPENAI_BASE_URL"),
    max_turns: Annotated[
        int,
        typer.Option("--max-turns", help="Maximum turns per task"),
    ] = 8,
    parallel: Annotated[
        int,
        typer.Option("--parallel", "-p", help="Number of parallel tasks"),
    ] = 1,
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Output directory (default: results/<model>)"),
    ] = None,
    system_prompt: Annotated[
        Optional[str],
        typer.Option("--system-prompt", help="Path to custom system prompt file"),
    ] = None,
    limit: Annotated[
        Optional[int],
        typer.Option("--limit", "-n", help="Limit number of tasks to run"),
    ] = None,
    offset: Annotated[
        int,
        typer.Option("--offset", help="Skip first N tasks"),
    ] = 0,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Verbose output"),
    ] = False,
) -> None:
    """Run OS Interaction evaluation tasks.

    Pass a JSON file for single-file mode, or the os_interaction directory for the full benchmark.

    Examples:
        # Single file
        ro-eval os-interaction data/dev.json --scripts scripts/dev

        # Full benchmark (156 tasks)
        ro-eval os-interaction ~/proj/AgentBench/data/os_interaction
    """
    # Load tasks - detect if path is a directory or file
    input_path = Path(data_path)

    if input_path.is_dir():
        # Full benchmark mode
        console.print(f"Loading full benchmark from {data_path}...")
        tasks = load_os_benchmark(data_path)
        console.print(f"Loaded {len(tasks)} tasks from benchmark")
    else:
        # Single file mode
        console.print(f"Loading tasks from {data_path}...")
        tasks = load_os_tasks(data_path, scripts_dir=scripts)
        console.print(f"Loaded {len(tasks)} tasks")

    # Apply offset and limit
    if offset > 0:
        tasks = tasks[offset:]
    if limit is not None:
        tasks = tasks[:limit]

    console.print(f"Running {len(tasks)} tasks (offset={offset}, limit={limit})")

    # Set default output directory if not specified
    if output is None:
        output_path = _default_output_dir(model, "os")
    else:
        output_path = Path(output)

    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    console.print(f"Results will be saved to: {output_path}")

    # Create config
    config = EvalConfig(
        model=model,
        base_url=base_url,
        max_turns=max_turns,
        parallel=parallel,
        output_dir=str(output_path),
        system_prompt_file=system_prompt,
        verbose=verbose,
    )

    # Create runner
    runner = EvalRunner(config, scripts_dir=scripts)

    # Run with progress bar
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TextColumn("({task.completed}/{task.total})"),
        console=console,
    ) as progress:
        task_id = progress.add_task("Running OS tasks...", total=len(tasks))

        def update_progress(completed: int, total: int) -> None:
            progress.update(task_id, completed=completed)

        # Run evaluation
        results, metrics = asyncio.run(
            runner.run_os_tasks(tasks, progress_callback=update_progress)
        )

    # Print summary
    console.print()
    console.print(print_summary(metrics))

    # Write results
    runs_path, overall_path, summary_path = write_results(results, metrics, str(output_path))
    console.print("\nResults written to:")
    console.print(f"  {runs_path}")
    console.print(f"  {overall_path}")
    console.print(f"  {summary_path}")


if __name__ == "__main__":
    app()
