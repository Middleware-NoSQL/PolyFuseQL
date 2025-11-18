import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class InsertStrategy(QueryStrategy):
    def _parse_literal_expression(self, lit_expr: exp.Literal) -> Any:
        """
        [Sonar Refactor S3776] Helper for InsertStrategy:
        Parses a sqlglot Literal expression into its Python equivalent,
        reducing the cognitive complexity of the 'execute' method.
        """
        if not isinstance(lit_expr, exp.Literal):
            # Fallback for unexpected types
            return lit_expr.this

        if lit_expr.is_string:
            return lit_expr.this

        val_str = lit_expr.this
        if not val_str:
            return None

        val_lower = val_str.lower()

        # Handle NULL
        if val_lower == "null":
            return None

        # Handle Booleans
        if val_lower == "true":
            return True
        if val_lower == "false":
            return False

        # Handle Numerics
        try:
            # Use Decimal for precision, consistent with other connector logic
            return Decimal(val_str)
        except InvalidOperation:
            # Fallback for any other unhandled literal (e.g., 'abc')
            msg = f"Could not parse literal '{val_str}' "
            msg += "as numeric, returning as string."
            logging.warning(msg)
            return val_str

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
        # if use_catalogue:
        #    catalogue_entry = client._catalogue.get(table_name)
        #    logging.info(f"Using catalogue: {catalogue_entry}")
        #    _, table = catalogue_entry
        # else:
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

        # [SONAR REFACTOR S3776] Replaced complex loop with a call
        # to the new helper method via list comprehension.
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
