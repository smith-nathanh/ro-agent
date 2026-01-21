"""Unrestricted MySQL handler for evaluation tasks.

Used for DBBench evaluation where the agent needs to execute mutations
and we need to calculate table hashes for evaluation.
"""

from typing import Any

import mysql.connector
from mysql.connector import Error as MySQLError

from ro_agent.tools.base import ToolHandler, ToolInvocation, ToolOutput
from ro_agent.tools.handlers.database import format_rows, DEFAULT_ROW_LIMIT


class UnrestrictedMySQLHandler(ToolHandler):
    """MySQL handler for DBBench evaluation.

    Allows all SQL operations and provides hash calculation for
    mutation query verification.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        row_limit: int = DEFAULT_ROW_LIMIT,
    ) -> None:
        """Initialize the MySQL handler.

        Args:
            host: MySQL server host
            port: MySQL server port
            user: MySQL username
            password: MySQL password
            database: Database name to use
            row_limit: Maximum number of rows to return in query results
        """
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._database = database
        self._row_limit = row_limit
        self._connection = None

    @property
    def name(self) -> str:
        return "execute_sql"

    @property
    def description(self) -> str:
        return (
            "Execute a SQL query against the database. "
            "You can run SELECT queries to retrieve data, or INSERT/UPDATE/DELETE "
            "to modify the database. Returns query results or confirmation of changes."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "The SQL query to execute",
                },
            },
            "required": ["sql"],
        }

    @property
    def requires_approval(self) -> bool:
        return False

    def _get_connection(self):
        """Get or create database connection."""
        if self._connection is None or not self._connection.is_connected():
            self._connection = mysql.connector.connect(
                host=self._host,
                port=self._port,
                user=self._user,
                password=self._password,
                database=self._database,
            )
        return self._connection

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        """Execute the SQL query."""
        sql = invocation.arguments.get("sql", "").strip()

        if not sql:
            return ToolOutput(content="No SQL query provided", success=False)

        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql)

            # Check if this is a SELECT query (has results)
            if cursor.description is not None:
                columns = [col[0] for col in cursor.description]
                rows = cursor.fetchall()

                # Limit rows
                rows = rows[: self._row_limit + 1]
                content = format_rows(columns, rows, self._row_limit)

                return ToolOutput(
                    content=content,
                    success=True,
                    metadata={
                        "columns": columns,
                        "row_count": min(len(rows), self._row_limit),
                        "truncated": len(rows) > self._row_limit,
                    },
                )
            else:
                # Non-SELECT query (INSERT, UPDATE, DELETE)
                conn.commit()
                rows_affected = cursor.rowcount

                return ToolOutput(
                    content=f"Query executed successfully. Rows affected: {rows_affected}",
                    success=True,
                    metadata={"rows_affected": rows_affected},
                )

        except MySQLError as e:
            return ToolOutput(
                content=f"SQL error: {e}",
                success=False,
            )
        except Exception as e:
            return ToolOutput(
                content=f"Error executing query: {e}",
                success=False,
            )

    def calculate_table_hash(self, table_info: dict, table_name: str) -> str | None:
        """Calculate MD5 hash of table state for mutation verification.

        Uses the same algorithm as AgentBench to compute a hash of all rows
        in the table, which can be compared against the pre-computed answer_md5.

        Args:
            table_info: Dict with 'columns' list containing column info
            table_name: Name of the table to hash

        Returns:
            MD5 hash string, or None if calculation fails
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # Build column list for CONCAT_WS
            columns = [f"`{col['name']}`" for col in table_info["columns"]]
            columns_str = ", ".join(columns)

            # AgentBench hash query:
            # SELECT MD5(GROUP_CONCAT(rowhash ORDER BY rowhash)) AS hash
            # FROM (
            #     SELECT SUBSTRING(MD5(CONCAT_WS(',', col1, col2, ...)), 1, 5) AS rowhash
            #     FROM `table_name`
            # ) AS sub
            query = (
                f"SELECT MD5(GROUP_CONCAT(rowhash ORDER BY rowhash)) AS hash "
                f"FROM ("
                f"SELECT SUBSTRING(MD5(CONCAT_WS(',', {columns_str})), 1, 5) AS rowhash "
                f"FROM `{table_name}`"
                f") AS sub"
            )

            cursor.execute(query)
            result = cursor.fetchone()

            if result and result[0]:
                return result[0]
            return None

        except Exception:
            return None
