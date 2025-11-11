import logging

from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class InsertStrategy(QueryStrategy):
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
        values = []
        for lit_expr in expressions.expressions:
            if lit_expr.is_string:
                values.append(lit_expr.this)
            else:
                val_str = lit_expr.this
                # Handle NULL and boolean literals
                if val_str.lower() == "null":
                    values.append(None)
                elif val_str.lower() in ("true", "false"):
                    values.append(val_str.lower() == "true")
                else:
                    # Handle numeric literals
                    try:
                        if "." in val_str:
                            values.append(float(val_str))
                        else:
                            values.append(int(val_str))
                    except (ValueError, TypeError):
                        # Fallback for any other unhandled literal type
                        values.append(val_str)

        payload = dict(zip(columns, values))
        conn = await client.get_connector(backend)
        logging.info(f"insert-strategy-payload: {payload}")
        logging.info(f"insert-strategy-table: {table}")
        logging.info(f"insert-strategy-backend: {backend}")
        return await conn.insert(table, payload)
