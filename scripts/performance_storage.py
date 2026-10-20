"""Performance-only SQL syntax extension; ownership stays in PrivateStorage."""
from source_test_storage import PrivateStorage


class PerformanceStorage(PrivateStorage):
    def guard(self, conn, cursor, statement, parameters, context, executemany):
        prefix = 'SELECT /*+ MAX_EXECUTION_TIME(15000) */ '
        if statement.startswith(prefix):
            # Strip only the reviewed fixed optimizer hint for the safety parser.
            # The executed SQL keeps its timeout; base checks actual UUID/database,
            # every relation, extra comments and multiple statements as usual.
            statement = 'SELECT ' + statement[len(prefix):]
        return super().guard(conn, cursor, statement, parameters, context, executemany)
