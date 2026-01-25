# Harbor Integration for TerminalBench

This directory contains the Harbor integration for running ro-agent on TerminalBench evaluations.

## What is TerminalBench?

TerminalBench is a benchmark for evaluating AI agents that operate exclusively through a terminal interface. The name refers to the **interface constraint**, not the task domain - all tasks must be solved using only command-line tools, with no GUI, browser, or IDE access.

### What it tests

TerminalBench measures whether an AI agent can accomplish real-world tasks given only a bash shell. This requires:

- **Tool discovery**: Knowing (or figuring out) which CLI tools to use
- **Command composition**: Chaining multiple tools together (pipes, scripts, etc.)
- **Error diagnosis**: Reading and debugging text-based error messages
- **System knowledge**: Understanding how Linux, networking, compilers, etc. work
- **Resourcefulness**: Installing packages, reading docs, adapting when things fail

Even tasks involving computer vision or databases must be solved through terminal commands - installing packages via apt/pip, running scripts, parsing output, and writing results to files.

### Why terminal-only?

The terminal constraint creates a consistent, reproducible evaluation environment:
- No ambiguity about what the agent can "see" or "click"
- Easy to sandbox in Docker containers
- Matches how many real automation and DevOps tasks work
- Tests genuine problem-solving rather than UI navigation

## How Harbor Works

[Harbor](https://github.com/laude-institute/harbor) is a framework for running AI agent benchmarks in isolated Docker containers.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Harbor Orchestrator                                        │
│  - Loads job config (job.yaml)                              │
│  - Downloads task definitions from registry                 │
│  - Spins up Docker containers per task                      │
│  - Runs agent, then verifier                                │
│  - Collects results                                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  Docker Container (per task)                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Task Environment                                    │   │
│  │  - Pre-configured with task-specific files           │   │
│  │  - /app contains the working directory               │   │
│  │  - instruction.md describes what to do               │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Agent (ro-agent)                                    │   │
│  │  - Reads instruction                                 │   │
│  │  - Executes bash commands, writes files              │   │
│  │  - Works until task complete or timeout              │   │
│  └─────────────────────────────────────────────────────┘   │
│                              │                              │
│                              ▼                              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  Verifier                                            │   │
│  │  - Runs task-specific tests                          │   │
│  │  - Outputs reward (0.0 or 1.0)                       │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### Execution flow

1. Harbor reads the job config and downloads tasks from the registry
2. For each task, Harbor starts a fresh Docker container with the task environment
3. The agent (`RoAgent`) is installed and runs with the task instruction
4. The agent executes commands, writes files, installs packages as needed
5. When the agent finishes (or times out), Harbor runs the verifier
6. The verifier checks if the task was completed correctly (reward = 0 or 1)
7. Results are logged to `~/proj/harbor/jobs/<timestamp>/`

## Running Evaluations

### Prerequisites

```bash
# From the harbor directory
cd ~/proj/harbor

# Install ro-agent as editable dependency
uv pip install -e ~/proj/ro-agent
```

### Configuration files

| File | Dataset | Tasks | Use case |
|------|---------|-------|----------|
| `job.yaml` | hello-world | 1 | Smoke test - verify setup works |
| `job-sample.yaml` | terminal-bench-sample | 10 | Quick evaluation across task types |
| `job-full.yaml` | terminal-bench | 89 | Full benchmark run |

### Running

```bash
cd ~/proj/harbor

# Smoke test (1 task)
uv run harbor run --config ~/proj/ro-agent/ro_agent/harbor/job.yaml

# Sample evaluation (10 tasks)
uv run harbor run --config ~/proj/ro-agent/ro_agent/harbor/job-sample.yaml

# Full benchmark (89 tasks)
uv run harbor run --config ~/proj/ro-agent/ro_agent/harbor/job-full.yaml
```

### Viewing results

Results are saved to `~/proj/harbor/jobs/<timestamp>/`:

```
jobs/2026-01-24__20-44-22/
├── config.json          # Job configuration
├── job.log              # Overall job log
├── result.json          # Aggregated results with reward stats
└── <task-name>__<id>/   # Per-task directory
    ├── trial.log        # Detailed execution log
    ├── result.json      # Task result with reward
    ├── agent/
    │   ├── agent_stdout.txt   # Agent's full output
    │   └── agent_stderr.txt   # Any errors
    └── verifier/
        ├── reward.txt         # Score (0 or 1)
        └── test-stdout.txt    # Test output
```

Browse results visually:
```bash
cd ~/proj/harbor
uv run harbor view
```

## Terminal-Bench-Sample Tasks (10 tasks)

| Task | Category | Difficulty | Description |
|------|----------|------------|-------------|
| **log-summary-date-ranges** | data-processing | medium | Analyze log files, count ERROR/WARNING/INFO by date ranges, output CSV |
| **fix-code-vulnerability** | security | hard | Find and fix CWE vulnerabilities in the Bottle web framework |
| **qemu-startup** | sys-admin | medium | Start Alpine Linux in QEMU, expose telnet on port 6665 |
| **regex-log** | data-processing | medium | Write regex to extract dates from log lines containing IPv4 addresses |
| **polyglot-c-py** | software-eng | medium | Create a file that runs as both Python and C, computing Fibonacci |
| **build-cython-ext** | debugging | medium | Fix pyknotid Cython extensions to work with NumPy 2.3.0 |
| **sqlite-with-gcov** | sys-admin | medium | Compile SQLite with gcov instrumentation |
| **chess-best-move** | games | medium | Analyze chess board image, find best move using Stockfish |
| **configure-git-webserver** | sys-admin | hard | Set up git server with post-receive hook to deploy to web server |
| **qemu-alpine-ssh** | sys-admin | medium | Start QEMU Alpine VM with SSH server accessible on port 2222 |

### Task categories

- **System administration** (4): QEMU VMs, git server setup, SQLite compilation
- **Data processing** (2): Log analysis, regex pattern matching
- **Security** (1): Vulnerability detection and fixing
- **Software engineering** (1): Polyglot C/Python code
- **Debugging** (1): Cython/NumPy compatibility issues
- **Games** (1): Computer vision + chess engine integration

## ro-agent Harbor Components

### Files

| File | Purpose |
|------|---------|
| `agent.py` | Harbor `BaseAgent` wrapper - handles setup and execution |
| `runner.py` | Entry point that runs inside the container |
| `tools/bash.py` | Unrestricted shell execution (container is sandbox) |
| `tools/write_file.py` | File creation/overwriting |
| `tools/edit_file.py` | Surgical file edits with fuzzy matching |

### How ro-agent runs in Harbor

1. **Setup phase** (`agent.py:setup`):
   - Uploads ro-agent source to `/ro-agent` in container
   - Installs uv and syncs dependencies

2. **Run phase** (`agent.py:run`):
   - Executes `runner.py` with the task instruction
   - Runner creates an agent with unrestricted tools (bash, write_file, edit_file)
   - Agent works in `/app` directory until complete or timeout

3. **Verification**:
   - Harbor runs task-specific tests
   - Reward written to `verifier/reward.txt`
