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
        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name)
            _, table = catalogue_entry
        else:
            table = table_name

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
        print("insert-strategy-payload", payload)
        print("insert-strategy-table", table)
        return await conn.insert(table, payload)
