from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class SelectStrategy(QueryStrategy):
    async def execute(self, client, ast, backend, use_catalogue):
        conn = client.backends.get(backend)
        if not conn:
            raise ValueError(f"Connector for backend '{backend}' not found.")

        is_agg = any(
            isinstance(e, exp.AggFunc)
            or (isinstance(e, exp.Alias) and isinstance(e.this, exp.AggFunc))
            for e in ast.expressions
        )

        # Case 1: Aggregation query with GROUP BY
        if ast.find(exp.Group):
            return await conn.group_by(ast)

        # Case 2: Aggregation query without GROUP BY
        if is_agg:
            return await conn.aggregate(ast)

        # Case 3: Simple SELECT...WHERE... query
        table_name = ast.find(exp.Table).name
        if ast.args.get("where"):
            where_expr = ast.args.get("where").this
        else:
            where_expr = None

        if not where_expr:
            raise NotImplementedError(
                "SELECT queries without a WHERE clause must be aggregations."
            )

        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name.lower())
            msg = f"Table '{table_name}' not found in catalogue."
            if not catalogue_entry:
                raise ValueError(msg)
            _, pk_col = catalogue_entry
        else:
            pk_col = str(where_expr.left.this)

        lit_expr = where_expr.right
        if not isinstance(lit_expr, exp.Literal):
            msg = "WHERE clause must compare to a literal value."
            raise NotImplementedError(msg)

        pk_val = (
            lit_expr.this
            if lit_expr.is_string
            else (
                int(lit_expr.this)
                if "." not in lit_expr.this
                else float(lit_expr.this)  # noqa: F501
            )
        )

        physical_table = ast.find(exp.Table).name
        result = await conn.get(physical_table, pk_col, pk_val)
        return [result] if result else []
