from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class SelectStrategy(QueryStrategy):
    async def execute(self, client, ast, backend, use_catalogue):
        conn = client.backends.get(backend)
        if not conn:
            raise ValueError(f"Connector for backend '{backend}' not found.")

        table_name = ast.find(exp.Table).name.lower()
        print("select-strategy-get-table_name", table_name)
        print("select-strategy-get-table_name-type", type(table_name))
        print("select-strategy-get-use_catalogue", use_catalogue)

        where_expr = ast.args.get("where").this
        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name)
            _, pk_col = catalogue_entry
        else:
            pk_col = str(where_expr.left.this)
        print("select-strategy-get-pk_col", pk_col)

        # --- START: Corrected Primary Key Value Extraction ---
        lit_expr = where_expr.right
        msg = "WHERE clause must compare to "
        msg += "a literal value (string or number)."  # noqa: F501
        if not isinstance(lit_expr, exp.Literal):
            raise NotImplementedError(msg)

        # Use sqlglot's properties to determine the type natively.
        if lit_expr.is_string:
            pk_val = lit_expr.this  # .this provides the unquoted string value
        else:
            # It's a number, so we safely convert it.
            try:
                pk_val = int(lit_expr.this)
            except ValueError:
                pk_val = float(lit_expr.this)
        # --- END: Corrected Primary Key Value Extraction ---

        physical_table = ast.find(exp.Table).name
        result = await conn.get(physical_table, pk_col, pk_val)
        return [result] if result else []
