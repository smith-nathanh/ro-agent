"""Tool handlers for ro-agent.

This module exports the standard 8-tool agentic toolkit plus database tools:

Core Tools (always available):
- ReadHandler (read) - Read file contents with line numbers
- GlobHandler (glob) - Find files by pattern using ripgrep
- GrepHandler (grep) - Search file contents using ripgrep
- ListHandler (list) - List directory contents
- ReadExcelHandler (read_excel) - Read Excel files

Mode-dependent Tools:
- BashHandler (bash) - Shell execution (restricted or unrestricted)
- WriteHandler (write) - File writing (off, create-only, or full)
- EditHandler (edit) - Surgical file editing (only with file_write=full)

Database Tools (enabled via env vars):
- OracleHandler (oracle)
- MysqlHandler (mysql)
- SqliteHandler (sqlite)
- VerticaHandler (vertica)
- PostgresHandler (postgres)

Backward Compatibility Aliases:
The following aliases are provided for existing code:
- ReadFileHandler -> ReadHandler
- FindFilesHandler -> GlobHandler
- SearchHandler -> GrepHandler
- ListDirHandler -> ListHandler
- ShellHandler -> BashHandler (restricted mode)
- WriteOutputHandler -> WriteHandler (create-only mode)
"""

# Core tools with new names
from .read import ReadHandler
from .glob import GlobHandler
from .grep import GrepHandler
from .list import ListHandler
from .read_excel import ReadExcelHandler

# Mode-dependent tools
from .bash import BashHandler
from .write import WriteHandler
from .edit import EditHandler

# Database tools
from .mysql import MysqlHandler
from .oracle import OracleHandler
from .postgres import PostgresHandler
from .sqlite import SqliteHandler
from .vertica import VerticaHandler

# Backward compatibility aliases (deprecated)
# TODO: Remove these in a future release
ReadFileHandler = ReadHandler
FindFilesHandler = GlobHandler
SearchHandler = GrepHandler
ListDirHandler = ListHandler
WriteOutputHandler = WriteHandler


class ShellHandler(BashHandler):
    """Backward compatibility alias for BashHandler in restricted mode.

    Deprecated: Use BashHandler(restricted=True) instead.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("restricted", True)
        super().__init__(**kwargs)

__all__ = [
    # New standard names
    "ReadHandler",
    "GlobHandler",
    "GrepHandler",
    "ListHandler",
    "ReadExcelHandler",
    "BashHandler",
    "WriteHandler",
    "EditHandler",
    # Database handlers
    "MysqlHandler",
    "OracleHandler",
    "PostgresHandler",
    "SqliteHandler",
    "VerticaHandler",
    # Backward compatibility (deprecated)
    "ReadFileHandler",
    "FindFilesHandler",
    "SearchHandler",
    "ListDirHandler",
    "ShellHandler",
    "WriteOutputHandler",
]
