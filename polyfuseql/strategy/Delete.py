from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class DeleteStrategy(QueryStrategy):
    async def execute(self, client, ast, backend, use_catalogue):
        conn = client.backends.get(backend)
        if not conn:
            raise ValueError(f"Connector for backend '{backend}' not found.")

        # Catalogue-based path:
        table_name = ast.find(exp.Table).name
        where_expr = ast.args.get("where").this

        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name)
            if not catalogue_entry:
                msg = f"Table '{table_name}' not found in catalogue."
                raise ValueError(msg)

            _, pk_col = catalogue_entry
        else:
            pk_col = str(where_expr.left.this)
        query_pk_col = where_expr.left.name

        if query_pk_col.lower() != pk_col.lower():
            msg = (
                f"DELETE on table '{table_name}' "
                f"must use the primary key '{pk_col}'."
            )  # noqa: F501
            raise ValueError(msg)

        lit_expr = where_expr.right
        if not isinstance(lit_expr, exp.Literal):
            msg = "DELETE WHERE clause requires a literal value."
            raise NotImplementedError(msg)

        if lit_expr.is_string:
            pk_val = lit_expr.this
        else:
            try:
                pk_val = int(lit_expr.this)
            except ValueError:
                pk_val = float(lit_expr.this)

        deleted_count = await conn.delete(table_name, pk_col, pk_val)
        return {"deleted_count": deleted_count, "backend": backend}
