"""Evaluation runner for AgentBench tasks."""

import asyncio
import uuid
from pathlib import Path
from typing import Any

from ro_agent.client.model import ModelClient
from ro_agent.core.agent import Agent
from ro_agent.core.session import Session
from ro_agent.tools.registry import ToolRegistry

from .config import (
    DBBenchResult,
    EvalConfig,
    EvalMetrics,
    OSResult,
    TaskResult,
    TaskStatus,
)
from .docker.container import EvalContainer
from .docker.mysql_container import MySQLContainer
from .evaluators.db_evaluator import DBBenchEvaluator
from .evaluators.os_evaluator import OSEvaluator
from .tasks.dbbench import DBBenchTask, create_sqlite_from_tableinfo
from .tasks.os_interaction import OSTask
from .tools.docker_shell import DockerShellHandler
from .tools.submit_answer import SubmitAnswerHandler, FinishActionHandler
from .tools.unrestricted_mysql import UnrestrictedMySQLHandler
from .tools.unrestricted_sqlite import UnrestrictedSqliteHandler


# System prompts for different task types
DBBENCH_SYSTEM_PROMPT = """I will ask you a question, then you should help me operate a database with SQL to answer the question.
You have to explain the problem and your solution to me and write down your thoughts.
After thinking and explaining thoroughly, every round you can choose to operate or to answer.

If you need to execute a SQL query, use the `execute_sql` tool. Your SQL should be in one line.
Every time you can only execute one SQL statement. I will execute it for you and give you the output.
If you are done operating, and you want to commit your final answer, use the `commit_final_answer` tool.

IMPORTANT RULES:
- Your answer should be accurate. Your answer must be EXACTLY the same as the correct answer.
- DO NOT add extra words, units, or explanations to your answer unless they are part of the expected value.
- If the answer is a number, just return the number. If it includes units in the data, include those exact units.
- If there is no matching result, answer "none" (just that word, nothing else).
- For modification queries (INSERT, UPDATE, DELETE), just submit "done" after completing the operation.
- DO NOT use commit_final_answer unless you are sure about your answer.
- Your final answer goes in the commit_final_answer tool, not in the text content.

Think step by step and explain your reasoning as you work."""

OS_SYSTEM_PROMPT = """You are a Linux system assistant. You will be given a task or question about a Linux system and must solve it by executing shell commands.

Available tools:
- bash_action: Execute a shell command in the Linux environment
- answer_action: Submit your answer when you have found it
- finish_action: Indicate the task is complete (for tasks without a specific answer)

Guidelines:
- Execute commands one at a time to investigate and solve the problem
- Your answers should be exact and precise (e.g., a number, a filename, a single word)
- Always use answer_action or finish_action to submit - don't just write the answer in text
- If output is truncated, adapt your approach to work with partial output

Think step by step about what information you need and how to obtain it."""


class EvalRunner:
    """Orchestrates running evaluation tasks through the agent."""

    def __init__(
        self,
        config: EvalConfig,
        scripts_dir: Path | str | None = None,
    ) -> None:
        """Initialize the evaluation runner.

        Args:
            config: Evaluation configuration
            scripts_dir: Optional path to check scripts directory
        """
        self.config = config
        self._scripts_dir = Path(scripts_dir) if scripts_dir else None
        self._db_evaluator = DBBenchEvaluator()
        self._os_evaluator = OSEvaluator(scripts_dir=scripts_dir)
        self._mysql_container: MySQLContainer | None = None

    async def _ensure_mysql(self) -> MySQLContainer:
        """Lazily start MySQL container on first use."""
        if self._mysql_container is None:
            self._mysql_container = MySQLContainer()
            await self._mysql_container.start()
        return self._mysql_container

    def _needs_mysql(self, task: DBBenchTask) -> bool:
        """Check if task requires MySQL for proper evaluation."""
        return (
            task.query_type in ("INSERT", "UPDATE", "DELETE")
            and task.answer_md5 is not None
        )

    async def cleanup(self) -> None:
        """Cleanup resources (call at end of eval run)."""
        if self._mysql_container:
            await self._mysql_container.cleanup()
            self._mysql_container = None

    async def run_dbbench_task(self, task: DBBenchTask) -> TaskResult:
        """Run a single DBBench task.

        Routes to MySQL for mutation queries with answer_md5, SQLite otherwise.

        Args:
            task: The DBBench task to run

        Returns:
            TaskResult with evaluation results
        """
        if self._needs_mysql(task):
            return await self._run_dbbench_task_mysql(task)
        return await self._run_dbbench_task_sqlite(task)

    async def _run_dbbench_task_sqlite(self, task: DBBenchTask) -> TaskResult:
        """Run a DBBench task using SQLite (for SELECT queries)."""
        db_path = None
        handler = None

        try:
            # Create temporary SQLite database
            db_path = create_sqlite_from_tableinfo(
                task.table_name,
                task.table_info,
            )

            # Create tool registry
            registry = ToolRegistry()
            handler = UnrestrictedSqliteHandler(db_path=db_path)
            registry.register(handler)

            # Create submit answer handler with answer capture
            submitted_answer: str | None = None

            def capture_answer(answer: str) -> None:
                nonlocal submitted_answer
                submitted_answer = answer

            submit_handler = SubmitAnswerHandler(
                tool_name="commit_final_answer",
                on_answer=capture_answer,
            )
            registry.register(submit_handler)

            # Create session and agent
            system_prompt = self._get_system_prompt("dbbench")
            session = Session(system_prompt=system_prompt)
            client = ModelClient(model=self.config.model, base_url=self.config.base_url)
            agent = Agent(
                session=session,
                registry=registry,
                client=client,
                auto_compact=False,  # Don't auto-compact during eval
            )

            # Run the task
            prompt = task.get_prompt()
            status = TaskStatus.COMPLETED
            turns = 0

            for turn in range(self.config.max_turns):
                turns += 1

                # Check if answer was submitted
                if submit_handler.is_submitted:
                    break

                # Run a turn
                try:
                    if turn == 0:
                        # First turn with the task prompt
                        async for event in agent.run_turn(prompt):
                            pass  # Process events silently
                    else:
                        # Subsequent turns - prompt agent to continue
                        async for event in agent.run_turn("Continue working on the task."):
                            pass

                    # Check for answer after turn
                    if submit_handler.is_submitted:
                        break

                except Exception as e:
                    if "context" in str(e).lower():
                        status = TaskStatus.AGENT_CONTEXT_LIMIT
                    else:
                        status = TaskStatus.TASK_ERROR
                    break

            # Check if we hit turn limit
            if turns >= self.config.max_turns and not submit_handler.is_submitted:
                status = TaskStatus.TASK_LIMIT_REACHED

            # Evaluate the answer
            is_correct = False
            if submitted_answer is not None:
                is_correct = self._db_evaluator.compare_results(
                    submitted_answer,
                    task.expected_answer,
                    task.query_type,
                )

            # Build result
            result = TaskResult(
                index=task.index,
                status=status,
                history=session.history.copy(),
                time=TaskResult.create_time(),
                result=DBBenchResult(
                    is_correct=is_correct,
                    answer=submitted_answer,
                    ground_truth=task.expected_answer,
                    std_sql=task.ground_truth_sql,
                    type=task.query_type,
                ),
            )

            return result

        except Exception as e:
            return TaskResult(
                index=task.index,
                status=TaskStatus.TASK_ERROR,
                history=[],
                time=TaskResult.create_time(),
                error=str(e),
            )

        finally:
            # Cleanup
            if handler:
                handler.close()
            if db_path and Path(db_path).exists():
                Path(db_path).unlink()

    async def _run_dbbench_task_mysql(self, task: DBBenchTask) -> TaskResult:
        """Run a DBBench mutation task using MySQL for hash-based evaluation."""
        handler = None
        db_name = f"eval_{task.index}_{uuid.uuid4().hex[:6]}"

        try:
            # Ensure MySQL container is running
            mysql = await self._ensure_mysql()

            # Create fresh database for this task
            await mysql.create_database(db_name)

            # Create tool registry with MySQL handler
            conn_info = mysql.get_connection_info()
            handler = UnrestrictedMySQLHandler(
                host=conn_info["host"],
                port=conn_info["port"],
                user=conn_info["user"],
                password=conn_info["password"],
                database=db_name,
            )

            # Initialize table with data
            await self._init_mysql_table(handler, task)

            registry = ToolRegistry()
            registry.register(handler)

            # Create submit answer handler
            submitted_answer: str | None = None

            def capture_answer(answer: str) -> None:
                nonlocal submitted_answer
                submitted_answer = answer

            submit_handler = SubmitAnswerHandler(
                tool_name="commit_final_answer",
                on_answer=capture_answer,
            )
            registry.register(submit_handler)

            # Create session and agent
            system_prompt = self._get_system_prompt("dbbench")
            session = Session(system_prompt=system_prompt)
            client = ModelClient(model=self.config.model, base_url=self.config.base_url)
            agent = Agent(
                session=session,
                registry=registry,
                client=client,
                auto_compact=False,
            )

            # Run the task
            prompt = task.get_prompt()
            status = TaskStatus.COMPLETED
            turns = 0

            for turn in range(self.config.max_turns):
                turns += 1

                if submit_handler.is_submitted:
                    break

                try:
                    if turn == 0:
                        async for event in agent.run_turn(prompt):
                            pass
                    else:
                        async for event in agent.run_turn("Continue working on the task."):
                            pass

                    if submit_handler.is_submitted:
                        break

                except Exception as e:
                    if "context" in str(e).lower():
                        status = TaskStatus.AGENT_CONTEXT_LIMIT
                    else:
                        status = TaskStatus.TASK_ERROR
                    break

            if turns >= self.config.max_turns and not submit_handler.is_submitted:
                status = TaskStatus.TASK_LIMIT_REACHED

            # For mutations, calculate table hash and compare to answer_md5
            table_hash = handler.calculate_table_hash(
                task.table_info.to_dict(),
                task.table_name,
            )
            is_correct = self._db_evaluator.compare_hash(table_hash, task.answer_md5)

            result = TaskResult(
                index=task.index,
                status=status,
                history=session.history.copy(),
                time=TaskResult.create_time(),
                result=DBBenchResult(
                    is_correct=is_correct,
                    answer=submitted_answer,
                    ground_truth=task.answer_md5,  # Store hash as ground truth for mutations
                    std_sql=task.ground_truth_sql,
                    type=task.query_type,
                ),
            )

            return result

        except Exception as e:
            return TaskResult(
                index=task.index,
                status=TaskStatus.TASK_ERROR,
                history=[],
                time=TaskResult.create_time(),
                error=str(e),
            )

        finally:
            if handler:
                handler.close()
            if self._mysql_container:
                await self._mysql_container.drop_database(db_name)

    async def _init_mysql_table(self, handler: UnrestrictedMySQLHandler, task: DBBenchTask) -> None:
        """Initialize MySQL table with task data."""
        from ro_agent.tools.base import ToolInvocation

        # Build CREATE TABLE statement
        col_defs = []
        for col in task.table_info.columns:
            col_name = f"`{col['name']}`"
            col_type = col.get("type", "TEXT").upper()
            if col_type in ("STRING", "VARCHAR", "CHAR"):
                col_type = "TEXT"
            col_defs.append(f"{col_name} {col_type}")

        create_sql = f"CREATE TABLE `{task.table_name}` ({', '.join(col_defs)})"

        await handler.handle(ToolInvocation(
            call_id="init_create",
            tool_name="execute_sql",
            arguments={"sql": create_sql},
        ))

        # Insert rows
        if task.table_info.rows:
            col_names = ", ".join(f"`{col['name']}`" for col in task.table_info.columns)
            placeholders = ", ".join("%s" for _ in task.table_info.columns)
            insert_sql = f"INSERT INTO `{task.table_name}` ({col_names}) VALUES ({placeholders})"

            conn = handler._get_connection()
            cursor = conn.cursor()
            cursor.executemany(insert_sql, task.table_info.rows)
            conn.commit()

    async def run_os_task(self, task: OSTask) -> TaskResult:
        """Run a single OS Interaction task.

        Args:
            task: The OS task to run

        Returns:
            TaskResult with evaluation results
        """
        container = None

        try:
            # Start Docker container
            container = EvalContainer(image=task.image)
            await container.start()

            # Run init code/file
            if task.init_code:
                await container.run_init(task.init_code)
            if task.init_file:
                await container.run_init_file(task.init_file)

            # Run background start script
            if task.start_script:
                await container.run_background(task.start_script)

            # Create tool registry
            registry = ToolRegistry()
            shell_handler = DockerShellHandler(container=container)
            registry.register(shell_handler)

            # Create submit answer handler
            submitted_answer: str | None = None
            finished = False

            def capture_answer(answer: str) -> None:
                nonlocal submitted_answer
                submitted_answer = answer

            def on_finish() -> None:
                nonlocal finished
                finished = True

            answer_handler = SubmitAnswerHandler(
                tool_name="answer_action",
                on_answer=capture_answer,
            )
            finish_handler = FinishActionHandler(on_finish=on_finish)
            registry.register(answer_handler)
            registry.register(finish_handler)

            # Create session and agent
            system_prompt = self._get_system_prompt("os")
            session = Session(system_prompt=system_prompt)
            client = ModelClient(model=self.config.model, base_url=self.config.base_url)
            agent = Agent(
                session=session,
                registry=registry,
                client=client,
                auto_compact=False,
            )

            # Run the task
            prompt = task.get_prompt()
            status = TaskStatus.COMPLETED
            turns = 0

            for turn in range(self.config.max_turns):
                turns += 1

                # Check if done
                if answer_handler.is_submitted or finish_handler.is_finished:
                    break

                # Run a turn
                try:
                    if turn == 0:
                        async for event in agent.run_turn(prompt):
                            pass
                    else:
                        async for event in agent.run_turn("Continue working on the task."):
                            pass

                    if answer_handler.is_submitted or finish_handler.is_finished:
                        break

                except Exception as e:
                    if "context" in str(e).lower():
                        status = TaskStatus.AGENT_CONTEXT_LIMIT
                    else:
                        status = TaskStatus.TASK_ERROR
                    break

            # Check turn limit
            if turns >= self.config.max_turns and not (
                answer_handler.is_submitted or finish_handler.is_finished
            ):
                status = TaskStatus.TASK_LIMIT_REACHED

            # Evaluate
            is_correct = await self._os_evaluator.evaluate(
                submitted_answer,
                task.evaluation,
                container,
                scripts_dir=task.scripts_dir,
            )

            result = TaskResult(
                index=task.index,
                status=status,
                history=session.history.copy(),
                time=TaskResult.create_time(),
                result=OSResult(result=is_correct),
            )

            return result

        except Exception as e:
            return TaskResult(
                index=task.index,
                status=TaskStatus.TASK_ERROR,
                history=[],
                time=TaskResult.create_time(),
                error=str(e),
            )

        finally:
            # Cleanup container
            if container:
                await container.cleanup()

    def _get_system_prompt(self, task_type: str) -> str:
        """Get the system prompt for a task type.

        If a custom prompt file is configured, load it. Otherwise use defaults.
        """
        if self.config.system_prompt_file:
            try:
                return Path(self.config.system_prompt_file).read_text()
            except Exception:
                pass  # Fall back to default

        if task_type == "dbbench":
            return DBBENCH_SYSTEM_PROMPT
        elif task_type == "os":
            return OS_SYSTEM_PROMPT
        else:
            return DBBENCH_SYSTEM_PROMPT

    async def run_dbbench_tasks(
        self,
        tasks: list[DBBenchTask],
        progress_callback: Any = None,
    ) -> tuple[list[TaskResult], EvalMetrics]:
        """Run multiple DBBench tasks with optional parallelism.

        Args:
            tasks: List of tasks to run
            progress_callback: Optional callback(completed, total) for progress

        Returns:
            Tuple of (results list, aggregate metrics)
        """
        metrics = EvalMetrics()
        results: list[TaskResult] = []

        # Create semaphore for parallelism
        semaphore = asyncio.Semaphore(self.config.parallel)

        async def run_with_semaphore(task: DBBenchTask) -> TaskResult:
            async with semaphore:
                return await self.run_dbbench_task(task)

        try:
            # Run tasks
            if self.config.parallel > 1:
                # Parallel execution
                pending = [run_with_semaphore(task) for task in tasks]
                for coro in asyncio.as_completed(pending):
                    result = await coro
                    results.append(result)

                    # Update metrics
                    is_correct = (
                        result.result.is_correct
                        if isinstance(result.result, DBBenchResult)
                        else False
                    )
                    metrics.add_result(result, is_correct)

                    if progress_callback:
                        progress_callback(len(results), len(tasks))
            else:
                # Sequential execution
                for task in tasks:
                    result = await self.run_dbbench_task(task)
                    results.append(result)

                    is_correct = (
                        result.result.is_correct
                        if isinstance(result.result, DBBenchResult)
                        else False
                    )
                    metrics.add_result(result, is_correct)

                    if progress_callback:
                        progress_callback(len(results), len(tasks))

            # Sort by index
            results.sort(key=lambda r: r.index)

        finally:
            # Cleanup MySQL container if it was started
            await self.cleanup()

        return results, metrics

    async def run_os_tasks(
        self,
        tasks: list[OSTask],
        progress_callback: Any = None,
    ) -> tuple[list[TaskResult], EvalMetrics]:
        """Run multiple OS tasks with optional parallelism.

        Args:
            tasks: List of tasks to run
            progress_callback: Optional callback(completed, total) for progress

        Returns:
            Tuple of (results list, aggregate metrics)
        """
        metrics = EvalMetrics()
        results: list[TaskResult] = []

        semaphore = asyncio.Semaphore(self.config.parallel)

        async def run_with_semaphore(task: OSTask) -> TaskResult:
            async with semaphore:
                return await self.run_os_task(task)

        if self.config.parallel > 1:
            pending = [run_with_semaphore(task) for task in tasks]
            for coro in asyncio.as_completed(pending):
                result = await coro
                results.append(result)

                is_correct = (
                    result.result.result
                    if isinstance(result.result, OSResult)
                    else False
                )
                metrics.add_result(result, is_correct)

                if progress_callback:
                    progress_callback(len(results), len(tasks))
        else:
            for task in tasks:
                result = await self.run_os_task(task)
                results.append(result)

                is_correct = (
                    result.result.result
                    if isinstance(result.result, OSResult)
                    else False
                )
                metrics.add_result(result, is_correct)

                if progress_callback:
                    progress_callback(len(results), len(tasks))

        results.sort(key=lambda r: r.index)

        return results, metrics
