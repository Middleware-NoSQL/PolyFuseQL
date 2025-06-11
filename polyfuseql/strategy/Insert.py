from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class InsertStrategy(QueryStrategy):
    async def execute(self, client, ast, backend, use_catalogue):
        """
        Executes an INSERT statement.

        Args:
            client: The PolyClient instance.
            ast: The AST for the INSERT statement.
            backend: The target backend.

        Returns:
            The result from the connector's insert method.
        """
        if not isinstance(ast, exp.Insert):
            raise ValueError("AST node is not an Insert expression")
        if use_catalogue:
            catalogue_entry = client.get_catalogue()
            _, table = catalogue_entry
        else:
            table = ast.this.this.name

        print("insert-strategy-table", table)
        print("insert-strategy-table-type", type(table))

        columns = [col.name for col in ast.this.expressions]

        # The values are nested inside a Values expression
        values_expression = ast.expression.find(exp.Values)
        if not values_expression:
            raise ValueError("No VALUES clause found in INSERT statement")

        # Assuming a single row insert for simplicity
        expressions = values_expression.expressions[0]
        values = [val.this for val in expressions.expressions]

        payload = dict(zip(columns, values))
        conn = client.backends[backend]
        return await conn.insert(table, payload)
