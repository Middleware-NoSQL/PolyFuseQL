from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class UpdateStrategy(QueryStrategy):
    async def execute(self, client, ast, backend, use_catalogue):
        table_name = ast.this.name
        where_expr = ast.args.get("where").this

        # Determine backend and primary key from catalogue
        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name.lower())
            if not catalogue_entry:
                msg = f"Table '{table_name}' not " f"found in catalogue."
                raise ValueError(msg)

            expected_backend, pk_col = catalogue_entry
            conn = client.backends.get(expected_backend)
        else:
            pk_col = where_expr.left.name
            conn = client.backends.get(backend)
            expected_backend = backend

        if not conn:
            msg = f"Connector for backend '{expected_backend}' not found."
            raise ValueError()

        # Extract primary key value from WHERE clause
        if where_expr.left.name != pk_col:
            print("update-where_expr.left.name", where_expr.left.name)
            print("update-where_expr.pk_col", pk_col)
            msg = (
                f"UPDATE on table '{table_name}' must use the "
                f"primary key '{pk_col}' in WHERE clause."
            )
            raise ValueError(msg)

        lit_expr = where_expr.right
        if lit_expr.is_string:
            pk_val = lit_expr.this
        else:
            try:
                pk_val = int(lit_expr.this)
            except ValueError:
                pk_val = float(lit_expr.this)

        # Extract SET expressions to build the payload
        payload = {}
        for expr in ast.expressions:
            if isinstance(expr, exp.EQ):
                col_name = expr.left.name
                val_expr = expr.right
                if val_expr.is_string:
                    payload[col_name] = val_expr.this
                else:
                    try:
                        payload[col_name] = int(val_expr.this)
                    except ValueError:
                        payload[col_name] = float(val_expr.this)
        print("update-strategy-table", table_name)
        print("update-strategy-pk_col", pk_col)
        print("update-strategy-pk_val", pk_val)
        print("update-strategy-payload", payload)
        print("update-strategy-backend", backend)
        print("update-strategy-use_catalogue", use_catalogue)
        print("update-strategy-conn", conn)
        updated_count = await conn.update(table_name, pk_col, pk_val, payload)
        return {"updated_count": updated_count, "backend": expected_backend}
