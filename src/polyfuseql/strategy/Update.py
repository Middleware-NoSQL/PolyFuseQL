import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class UpdateStrategy(QueryStrategy):
    def _parse_literal_expression(self, lit_expr: exp.Literal) -> Any:
        """
        [Sonar Refactor S3776] Helper for UpdateStrategy:
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

    def _build_update_payload(self, set_expressions: list[exp.EQ]) -> dict:
        """
        [Sonar Refactor S3776] Helper for UpdateStrategy:
        Builds the update payload dict from the SET expressions.
        """
        payload = {}
        for expr in set_expressions:
            if isinstance(expr, exp.EQ):
                col_name = expr.left.name
                # Use the parser for the value
                payload[col_name] = self._parse_literal_expression(expr.right)
        return payload

    async def _get_connector_and_pk(self, client, ast, backend, use_catalogue):
        """
        [Sonar Refactor S3776] Helper for UpdateStrategy:
        Gets the correct connector and PK column based on the catalogue.
        """
        table_name = ast.this.name
        where_expr = ast.args.get("where").this

        if use_catalogue:
            catalogue_entry = client._catalogue.get(table_name.lower())
            if not catalogue_entry:
                msg = f"Table '{table_name}' not found in catalogue."
                raise ValueError(msg)

            expected_backend = (
                catalogue_entry.get("backend") if not backend else backend
            )
            pk_col = catalogue_entry.get("pk")
            if not pk_col:
                raise ValueError(
                    f"No 'pk' defined in catalogue for table '{table_name}'"
                )

            conn = await client.get_connector(expected_backend)
        else:
            pk_col = where_expr.left.name
            conn = await client.get_connector(backend)
            expected_backend = backend

        if not conn:
            msg = f"Connector for backend '{expected_backend}' not found."
            raise ValueError(msg)

        return conn, pk_col, expected_backend

    async def execute(self, client, ast, backend, use_catalogue):
        """
        [Sonar Refactor] Executes an UPDATE statement.
        Delegates complex logic to helpers to maintain low complexity.
        """
        table_name = ast.this.name
        where_expr = ast.args.get("where").this

        # 1. Get connector and PK
        conn, pk_col, expected_backend = await self._get_connector_and_pk(
            client, ast, backend, use_catalogue
        )

        # 2. Validate WHERE clause
        if where_expr.left.name != pk_col:
            logging.info(f"update-where_expr.left.name {where_expr.left.name}")
            logging.info(f"update-where_expr.pk_col {pk_col}")
            msg = (
                f"UPDATE on table '{table_name}' must use the "
                f"primary key '{pk_col}' in WHERE clause."
            )
            raise ValueError(msg)

        # 3. Parse PK value from WHERE clause
        pk_val = self._parse_literal_expression(where_expr.right)

        # 4. Build payload from SET expressions
        payload = self._build_update_payload(ast.expressions)

        # 5. Execute
        logging.info(f"update-strategy-table: {table_name}")
        logging.info(f"update-strategy-pk_col: {pk_col}")
        logging.info(f"update-strategy-pk_val: {pk_val}")
        logging.info(f"update-strategy-payload: {payload}")
        logging.info(f"update-strategy-backend: {expected_backend}")

        updated_count = await conn.update(table_name, pk_col, pk_val, payload)
        return {"updated_count": updated_count, "backend": expected_backend}
