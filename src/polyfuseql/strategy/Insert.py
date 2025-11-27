import logging
from polyfuseql.strategy.Query import QueryStrategy
from polyfuseql.strategy.LiteralParser import LiteralParser
from sqlglot import exp


class InsertStrategy(QueryStrategy, LiteralParser):
    async def execute(self, client, ast, backend, use_catalogue):
        """
        Executes an INSERT statement.

        Args:
            :param backend: The target backend.
            :param ast: The AST for the INSERT statement.
            :param client: The PolyClient instance.
            :param use_catalogue: Flag to indicate whether to use catalogue.

        Returns:
            The result from the connector's insert method.
        """

        table_name = ast.find(exp.Table).name

        if not isinstance(ast, exp.Insert):
            raise ValueError("AST node is not an Insert expression")

        table = table_name

        logging.info(f"insert-strategy-table {table}")
        logging.info(f"insert-strategy-table-type {type(table)}")

        columns = [col.name for col in ast.this.expressions]

        # The values are nested inside a Values expression
        values_expression = ast.expression.find(exp.Values)
        if not values_expression:
            raise ValueError("No VALUES clause found in INSERT statement")

        # Assuming a single row insert for simplicity
        expressions = values_expression.expressions[0]

        # [SONAR REFACTOR] Replaced complex loop with a call
        # to the inherited helper method via list comprehension.
        values = [
            self._parse_literal_expression(expr)
            for expr in expressions.expressions  # noqa:E501
        ]

        payload = dict(zip(columns, values))
        conn = await client.get_connector(backend)
        logging.info(f"insert-strategy-payload: {payload}")
        logging.info(f"insert-strategy-table: {table}")
        logging.info(f"insert-strategy-backend: {backend}")
        return await conn.insert(table, payload)
