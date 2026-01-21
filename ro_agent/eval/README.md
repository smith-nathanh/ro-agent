# AgentBench Evaluation Module

This module runs [AgentBench](https://github.com/THUDM/AgentBench) tasks through ro-agent's harness to evaluate LLM performance on database queries (DBBench) and Linux system tasks (OS Interaction).

## Quick Start

```bash
# Run DBBench (database tasks)
ro-eval dbbench ~/proj/AgentBench/data/dbbench/standard.jsonl --model gpt-4o

# Run OS Interaction (Linux tasks) - requires Docker
ro-eval os-interaction ~/proj/AgentBench/data/os_interaction/data/dev.json \
  --scripts ~/proj/AgentBench/data/os_interaction/scripts/dev \
  --model gpt-4o
```

## Commands

### `ro-eval dbbench`

Runs database query tasks. The agent must answer questions about data by executing SQL queries.

```bash
ro-eval dbbench DATA_FILE [OPTIONS]

Arguments:
  DATA_FILE              Path to standard.jsonl from AgentBench

Options:
  -m, --model TEXT       Model to use (default: gpt-4o)
  --base-url TEXT        API base URL for OpenAI-compatible endpoints
  --max-turns INTEGER    Max turns per task (default: 20)
  -p, --parallel INTEGER Run N tasks in parallel (default: 1)
  -o, --output TEXT      Output directory for results
  -n, --limit INTEGER    Only run first N tasks
  --offset INTEGER       Skip first N tasks
  --system-prompt TEXT   Path to custom system prompt file
```

### `ro-eval os-interaction`

Runs Linux system tasks. The agent must solve problems by executing shell commands in a Docker container.

```bash
ro-eval os-interaction DATA_FILE [OPTIONS]

Arguments:
  DATA_FILE              Path to task JSON file (e.g., dev.json)

Options:
  -s, --scripts TEXT     Path to check scripts directory
  -m, --model TEXT       Model to use (default: gpt-4o)
  --base-url TEXT        API base URL for OpenAI-compatible endpoints
  --max-turns INTEGER    Max turns per task (default: 8)
  -p, --parallel INTEGER Run N tasks in parallel (default: 1)
  -o, --output TEXT      Output directory for results
  -n, --limit INTEGER    Only run first N tasks
  --offset INTEGER       Skip first N tasks
```

**Prerequisites for OS tasks:**
- Docker must be installed and running
- AgentBench Docker images must be built (`local-os/default`, `local-os/packages`, `local-os/ubuntu`)

## How It Works

### DBBench Flow

1. **Task Loading**: Parses `standard.jsonl` to extract questions, table schemas, and expected answers
2. **Database Setup**: Creates a temporary SQLite database from the task's table info
3. **Agent Execution**: Runs the agent with two tools:
   - `execute_sql`: Run any SQL query (SELECT, INSERT, UPDATE, DELETE)
   - `commit_final_answer`: Submit the final answer
4. **Evaluation**: Compares the submitted answer to ground truth using:
   - Float tolerance (±0.01) for numeric values
   - Set comparison for multiple values
   - Exact match for mutation query results
5. **Cleanup**: Deletes the temporary database

### OS Interaction Flow

1. **Task Loading**: Parses JSON task file with descriptions and evaluation configs
2. **Container Setup**: Starts a Docker container with the specified image
3. **Initialization**: Runs init scripts and starts background processes
4. **Agent Execution**: Runs the agent with three tools:
   - `bash_action`: Execute any shell command in the container
   - `answer_action`: Submit the final answer
   - `finish_action`: Mark task complete (for action-based tasks)
5. **Evaluation**: Checks the answer using:
   - Direct string match (`match` type)
   - Check scripts like `integer-match.py`, `string-match.py` (`check` type)
6. **Cleanup**: Stops and removes the Docker container

### System Prompts

The agent receives task-specific system prompts:

**DBBench prompt** instructs the agent to:
- Explore data with SELECT queries first
- Execute SQL to find answers
- Use `commit_final_answer` to submit

**OS prompt** instructs the agent to:
- Execute commands one at a time
- Provide exact, precise answers
- Use `answer_action` or `finish_action` to complete

Custom prompts can be provided via `--system-prompt path/to/prompt.md`.

## Output Format

Results are written in AgentBench-compatible format:

### `runs.jsonl`

One JSON object per line with task results:

```json
{
  "index": 0,
  "status": "completed",
  "result": {
    "is_correct": true,
    "answer": "42",
    "ground_truth": ["42"],
    "std_sql": "SELECT COUNT(*) FROM users",
    "type": "SELECT"
  },
  "history": [
    {"role": "system", "content": "..."},
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "content": "..."}
  ],
  "time": {"timestamp": 1705849200, "str": "2024-01-21 15:00:00"}
}
```

### `overall.json`

Aggregate metrics:

```json
{
  "total": 300,
  "validation": {
    "completed": 0.85,
    "agent context limit": 0.03,
    "agent validation failed": 0.02,
    "agent invalid action": 0.01,
    "task limit reached": 0.05,
    "task error": 0.02,
    "unknown": 0.02,
    "average_history_length": 4.5,
    "max_history_length": 20,
    "min_history_length": 2
  },
  "custom": {
    "overall": {
      "total": 300,
      "pass": 255,
      "wrong": 45,
      "acc": 0.85
    }
  }
}
```

## Examples

### Run a quick smoke test

```bash
# First 10 DBBench tasks
ro-eval dbbench data/dbbench/standard.jsonl -n 10 -o smoke_test/

# First 5 OS tasks
ro-eval os-interaction data/os_interaction/data/dev.json -n 5 -o smoke_test/
```

### Run with a different model

```bash
# Use Claude via OpenRouter
ro-eval dbbench data.jsonl \
  --model anthropic/claude-3.5-sonnet \
  --base-url https://openrouter.ai/api/v1

# Use local Ollama
ro-eval dbbench data.jsonl \
  --model llama3.1 \
  --base-url http://localhost:11434/v1
```

### Parallel execution

```bash
# Run 4 DBBench tasks in parallel
ro-eval dbbench data.jsonl -p 4 -o results/

# Run 2 OS tasks in parallel (limited by Docker resources)
ro-eval os-interaction data.json -p 2 -o results/
```

### Resume from a specific task

```bash
# Skip first 100 tasks, run next 50
ro-eval dbbench data.jsonl --offset 100 -n 50 -o results/
```

## Architecture

```
ro_agent/eval/
├── cli.py                 # Typer CLI commands
├── runner.py              # EvalRunner orchestrates execution
├── config.py              # EvalConfig, TaskResult, EvalMetrics
├── output.py              # Result formatting
│
├── tasks/
│   ├── base.py            # BaseTask ABC
│   ├── dbbench.py         # DBBench task loader
│   └── os_interaction.py  # OS task loader
│
├── tools/
│   ├── submit_answer.py   # commit_final_answer, answer_action, finish_action
│   ├── unrestricted_sqlite.py  # SQL execution without read-only limits
│   ├── unrestricted_shell.py   # Shell without command allowlist
│   └── docker_shell.py    # Shell execution in Docker container
│
├── evaluators/
│   ├── db_evaluator.py    # DBBench answer comparison (ported from AgentBench)
│   └── os_evaluator.py    # Check script execution
│
└── docker/
    └── container.py       # Docker container lifecycle
```

## Comparison with AgentBench

| Feature | AgentBench | ro-agent eval |
|---------|------------|---------------|
| Database backend | MySQL | SQLite (in-memory) |
| Container runtime | Docker | Docker |
| Agent framework | Custom | ro-agent core |
| Parallelism | Multi-process | asyncio + semaphore |
| Output format | Compatible | Compatible |
| Check scripts | Python scripts | Built-in + script support |