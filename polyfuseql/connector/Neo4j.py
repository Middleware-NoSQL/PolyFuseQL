import logging
from datetime import datetime, date
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
from neo4j import AsyncGraphDatabase as AGD, AsyncDriver, time as neo_time
from polyfuseql.utils.utils import env, _camelize_keys, get_pydantic_model
from sqlglot import exp
import csv
import itertools
from pydantic import ValidationError
from decimal import Decimal


class Neo4jConnector(Connector):
    """Connector for Neo4j with persistent connection handling."""

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        driver = self._get_driver()
        cypher_query = f"MATCH (n:{entity.capitalize()}) "
        cypher_query += "RETURN properties(n) as p"
        async with driver.session() as s:
            result = await s.run(cypher_query)
            return [rec["p"] async for rec in result]

    def __init__(self, options: Optional[Dict] = None) -> None:
        super().__init__(options)
        host = env("NEO4J_HOST", "localhost")
        port = env("NEO4J_PORT", "7687")
        user = env("NEO4J_USER", "neo4j")
        password = env("NEO4J_PASSWORD", "password")
        self._uri = f"bolt://{host}:{port}"
        self._auth = (user, password)
        self._driver: Optional[AsyncDriver] = None

    async def connect(self) -> None:
        if not self._driver:
            self._driver = AGD.driver(self._uri, auth=self._auth)
            logging.info("Neo4j driver initialized.")
            await self.ping()

    async def disconnect(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            logging.info("Neo4j driver closed.")

    def _get_driver(self) -> AsyncDriver:
        if not self._driver:
            raise ConnectionError(
                "Neo4jConnector is not connected. Call connect() first."
            )
        return self._driver

    async def ping(self) -> bool:
        driver = self._get_driver()
        async with driver.session() as s:
            await s.run("RETURN 1")
        return True

    async def count(self, label: str) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            query = f"MATCH (n:{label.capitalize()}) RETURN count(n) AS n"
            result = await s.run(query)
            rec = await result.single()
            return rec["n"] if rec else 0

    async def get(
        self, label: str, pk_col: str, pk_val: Any
    ) -> Dict[str, Any]:  # noqa: F501
        driver = self._get_driver()
        async with driver.session() as s:
            cypher_match = f"MATCH (n:{label.capitalize()}) "
            cypher_where = f"WHERE n.`{pk_col}` "  # noqa: F501
            cypher = (
                cypher_match
                + cypher_where
                + "= $pk_val RETURN properties(n) AS p LIMIT 1"
            )
            result = await s.run(cypher, pk_val=pk_val)
            rec = await result.single()
            return rec["p"] if rec and rec["p"] else {}

    async def insert(self, label: str, payload: Dict[str, Any]) -> Any:
        driver = self._get_driver()
        props = ", ".join(f"`{k}`: ${k}" for k in payload.keys())

        cypher = f"CREATE (n:{label.capitalize()} {{ {props} }}) "
        cypher += "RETURN properties(n) as p"
        async with driver.session() as s:
            result = await s.run(cypher, **payload)
            rec = await result.single()
            return rec["p"] if rec else {}

    async def query(
        self, sql: str, params: Optional[tuple] = None
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "Neo4jConnector expects Cypher, not SQL, for generic queries."
        )

    async def delete(self, label: str, pk_col: str, pk_val: Any) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            cypher = (
                f"MATCH (n:{label.capitalize()} {{{pk_col}: $pk_val}}) "
                "DETACH DELETE n"
            )
            summary = await s.run(cypher, pk_val=pk_val)
            return 1 if summary else 0

    async def update(
        self, label: str, pk_col: str, pk_val: Any, payload: Dict[str, Any]
    ) -> int:
        driver = self._get_driver()
        async with driver.session() as s:
            cypher = f"MATCH (n:{label} {{`{pk_col}`: $pk_val}}) "
            cypher += "SET n += $payload"
            summary = await s.run(cypher, pk_val=pk_val, payload=payload)
            return 1 if summary else 0

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Manually translates a SQL JOIN AST to a Cypher query."""
        driver = self._get_driver()

        left_table_expr = ast.args.get("from").this
        join_expr = ast.args.get("joins")[0]
        right_table_expr = join_expr.this
        on_condition = join_expr.args.get("on")

        left_table_name = left_table_expr.this.name.capitalize()
        left_alias = left_table_expr.alias_or_name
        right_table_name = right_table_expr.this.name.capitalize()
        right_alias = right_table_expr.alias_or_name

        match_clause = (
            f"MATCH ({left_alias}:{left_table_name}), "
            f"({right_alias}:{right_table_name})"
        )
        on_left = f"{on_condition.this.table}.{on_condition.this.this.name}"
        on_right = f"{on_condition.expression.table}."
        on_right += f"{on_condition.expression.this.name}"
        where_clauses = [f"{on_left} = {on_right}"]

        params = {}
        if ast.args.get("where"):
            where_expr = ast.args["where"].this
            where_col = f"{where_expr.this.table}.{where_expr.this.this.name}"
            where_clauses.append(f"{where_col} = $where_val")

            lit_expr = where_expr.expression
            if lit_expr.is_string:
                params["where_val"] = lit_expr.this
            else:
                try:
                    params["where_val"] = int(lit_expr.this)
                except ValueError:
                    params["where_val"] = float(lit_expr.this)

        where_clause_str = " WHERE " + " AND ".join(where_clauses)

        return_expressions = []
        for col_expr in ast.expressions:
            col_name = col_expr.this.name
            table_alias = col_expr.table
            return_alias = f"`{col_name}`"
            exp_str = f"{table_alias}.{col_name} AS {return_alias}"
            return_expressions.append(exp_str)

        return_clause_str = "RETURN " + ", ".join(return_expressions)
        cypher_query = f"{match_clause}{where_clause_str} {return_clause_str}"

        async with driver.session() as s:
            result = await s.run(cypher_query, **params)
            return [dict(record) async for record in result]

    def _evaluate_expression(self, expr, row_data, interpret_numeric=True):
        """Helper method to recursively evaluate
        a sqlglot expression against a data row."""
        if isinstance(expr, exp.Paren):
            return self._evaluate_expression(expr.this, row_data)
        if isinstance(expr, exp.Column):
            val = row_data.get(expr.sql())
            if interpret_numeric:
                try:
                    return Decimal(val) if val is not None else Decimal(0)
                except (ValueError, TypeError):
                    return Decimal(0)
            return val
        if isinstance(expr, exp.Literal):
            return Decimal(expr.this)
        if isinstance(expr, exp.Mul):
            return self._evaluate_expression(
                expr.left, row_data
            ) * self._evaluate_expression(expr.right, row_data)
        if isinstance(expr, exp.Sub):
            return self._evaluate_expression(
                expr.left, row_data
            ) - self._evaluate_expression(expr.right, row_data)
        if isinstance(expr, exp.Add):
            return self._evaluate_expression(
                expr.left, row_data
            ) + self._evaluate_expression(expr.right, row_data)
        raise NotImplementedError(f"Unsupported expression: {type(expr)}")

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Performs an application-side GROUP BY on data fetched from Neo4j."""
        table_name = ast.find(exp.Table).name

        all_data = await self.get_all(table_name)

        # Application-side WHERE clause filtering
        if ast.args.get("where"):
            where_expr = ast.args["where"].this
            if isinstance(where_expr, exp.LTE):
                col = where_expr.left.sql()
                date_val = where_expr.right.sql()
                date_str = date_val.split("'")[1]
                threshold_date = datetime.strptime(date_str, "%Y-%m-%d").date()

                filtered_data = []
                for row in all_data:
                    r_date = row.get(col)
                    row_date = None
                    if isinstance(r_date, neo_time.Date):
                        row_date = date(r_date.year, r_date.month, r_date.day)
                    elif isinstance(r_date, str):
                        row_date = datetime.strptime(r_date, "%Y-%m-%d").date()

                    if row_date and row_date <= threshold_date:
                        filtered_data.append(row)
                all_data = filtered_data

        if not all_data:
            return []

        group_by_cols = [e.sql() for e in ast.args.get("group").expressions]
        all_data.sort(key=lambda x: tuple(x.get(col) for col in group_by_cols))

        results = []
        for key, group_iter in itertools.groupby(
            all_data, key=lambda x: tuple(x.get(col) for col in group_by_cols)
        ):
            group = list(group_iter)
            result_row = {}

            # Populate the result row with all expressions
            # from the SELECT clause
            for expr in ast.expressions:
                alias = expr.alias_or_name

                # Handle grouping columns
                if isinstance(expr, exp.Column):
                    result_row[alias] = group[0].get(expr.sql())
                    continue

                # Handle aggregations
                if isinstance(expr, exp.Alias):
                    agg_func = expr.this

                    if isinstance(agg_func, exp.Count):
                        result_row[alias] = len(group)
                    elif isinstance(agg_func, exp.Sum):
                        v = [
                            self._evaluate_expression(agg_func.this, row)
                            for row in group
                        ]
                        result_row[alias] = sum(v)
                    elif isinstance(agg_func, exp.Avg):
                        v = [
                            self._evaluate_expression(agg_func.this, row)
                            for row in group
                        ]
                        result_row[alias] = Decimal(0)
                        if v:
                            result_row[alias] = sum(v) / Decimal(len(v))

            results.append(result_row)

        return [_camelize_keys(row) for row in results]

    async def aggregate(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """
        Translates a SQL aggregation query (no GROUP BY) to a Cypher query.
        This version correctly handles aliased and non-aliased aggregations.
        """
        driver = self._get_driver()

        table_name = ast.find(exp.Table).name.capitalize()
        node_alias = "n"
        match_clause = f"MATCH ({node_alias}:{table_name})"

        return_items = []
        # Iterate over each expression in the
        # SELECT clause (e.g., "SUM(amount) AS total")
        for expr in ast.expressions:
            # Determine the alias for the final result column
            alias = expr.alias_or_name

            # Isolate the core expression (e.g., the SUM(...) part)
            core_expr = expr.this if isinstance(expr, exp.Alias) else expr

            # Ensure we are dealing with an aggregation
            # function like SUM, AVG, COUNT
            if isinstance(core_expr, exp.AggFunc):
                func_name = core_expr.name.lower()

                # Special case for COUNT(*)
                if isinstance(core_expr, exp.Count) and isinstance(
                    core_expr.this, exp.Star
                ):
                    return_items.append(f"count(*) AS `{alias}`")
                # Case for other aggregations like SUM(column), AVG(column)
                elif core_expr.this:
                    # Translate the inner part of the aggregation,
                    # e.g., the `amount` in `SUM(amount)`
                    inner_expr_str = self._translate_agg_expression(
                        core_expr.this, node_alias
                    )
                    expr_str = f"{func_name}({inner_expr_str}) AS `{alias}`"
                    return_items.append(expr_str)
                else:
                    raise NotImplementedError(
                        f"Unsupported aggregation function: {core_expr.sql()}"
                    )
            else:
                msg = "Non-aggregation expression found"
                msg += f" in aggregate query: {expr.sql()}"
                raise NotImplementedError(msg)

        if not return_items:
            msg = "Could not translate any expressions "
            msg += "from the SQL query into Cypher."
            raise ValueError(msg)

        return_clause = "RETURN " + ", ".join(return_items)
        cypher_query = f"{match_clause} {return_clause}"

        logging.debug(f"Executing translated Cypher query: {cypher_query}")

        async with driver.session() as s:
            result = await s.run(cypher_query)
            raw_results = [dict(record) async for record in result]

            # If Neo4j returns a list of values instead of
            # a single aggregated value,
            # perform the summation here in Python as a fallback.
            if not raw_results:
                alias = ast.expressions[0].alias_or_name
                return [{_camelize_keys({alias: 0})[alias]: 0.0}]

            alias_from_db = list(raw_results[0].keys())[0]

            # Check if the result is already aggregated. If so, just return it.
            if len(raw_results) == 1 and isinstance(
                raw_results[0][alias_from_db], (int, float)
            ):
                return [_camelize_keys(row) for row in raw_results]

            # Otherwise, perform the aggregation in Python
            alias = ast.expressions[0].alias_or_name
            agg_func = ast.expressions[0].this

            values = [
                float(row[alias_from_db])
                for row in raw_results
                if row.get(alias_from_db) is not None
            ]

            final_value = 0.0
            if isinstance(agg_func, exp.Sum):
                final_value = sum(values)
            elif isinstance(agg_func, exp.Avg):
                final_value = sum(values) / len(values) if values else 0.0
            elif isinstance(agg_func, exp.Count):
                final_value = len(values)

            final_result = [{alias: final_value}]

            return [_camelize_keys(row) for row in final_result]

    def _translate_agg_expression(self, expr, node_alias):
        """Recursively translates a sqlglot expression into a Cypher string."""
        if isinstance(expr, exp.Paren):
            return f"({self._translate_agg_expression(expr.this, node_alias)})"
        if isinstance(expr, exp.Column):
            return f"toFloat({node_alias}.{expr.sql()})"
        if isinstance(expr, exp.Literal):
            return expr.sql()
        if isinstance(expr, exp.Mul):
            left = self._translate_agg_expression(expr.left, node_alias)
            right = self._translate_agg_expression(expr.right, node_alias)
            return f"({left} * {right})"
        if isinstance(expr, exp.Sub):
            left = self._translate_agg_expression(expr.left, node_alias)
            right = self._translate_agg_expression(expr.right, node_alias)
            return f"({left} - {right})"
        if isinstance(expr, exp.Add):
            left = self._translate_agg_expression(expr.left, node_alias)
            right = self._translate_agg_expression(expr.right, node_alias)
            return f"({left} + {right})"
        raise NotImplementedError(
            f"Unsupported expression type in aggregation: {type(expr)}"
        )

    async def bulk_insert(
        self, table_name: str, file_path: str, batch_size: int = 5000
    ) -> tuple[int, int]:
        """
        Performs a high-performance bulk insert using batched
        UNWIND operations.
        """
        driver = self._get_driver()
        schema = TPCH_SCHEMA.get(table_name.lower())
        if not schema:
            msg = f"No schema definition found for table: {table_name}"
            raise ValueError(msg)

        cols = schema["columns"]
        label = table_name.capitalize()

        DynamicModel = get_pydantic_model(table_name, schema)

        async with driver.session() as s:
            await s.run(f"MATCH (n:{label}) DETACH DELETE n")

        props_str = ", ".join([f"{col}: row.{col}" for col in cols])
        cypher_query = f"""
        CALL {{
            UNWIND $rows AS row
            CREATE (n:{label} {{ {props_str} }})
        }} IN TRANSACTIONS OF 1000 ROWS
        """

        total_inserted = 0
        total_lines = 0
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                reader = csv.reader(f, delimiter="|")
                batch = []
                for line in reader:
                    if not line:
                        continue
                    line = line[: len(cols)]
                    if len(line) < len(cols):
                        logging.warning(
                            f"Skipping malformed row in {file_path}: {line}"
                        )
                        continue
                    total_lines += 1

                    try:
                        row_dict = dict(zip(cols, line))
                        validated_data = DynamicModel(**row_dict)

                        model_dict = validated_data.model_dump()
                        for key, value in model_dict.items():
                            if isinstance(value, date):
                                model_dict[key] = neo_time.Date(
                                    value.year, value.month, value.day
                                )
                        batch.append(model_dict)
                    except ValidationError as e:
                        msg = "Skipping row due to validation"
                        msg += f" error: {line}. Error: {e}"

                        logging.warning(msg)
                        continue

                    if len(batch) >= batch_size:
                        async with driver.session() as s:
                            result = await s.run(cypher_query, rows=batch)
                            summary = await result.consume()
                            total_inserted += summary.counters.nodes_created
                        batch = []

                if batch:
                    async with driver.session() as s:
                        result = await s.run(cypher_query, rows=batch)
                        summary = await result.consume()
                        total_inserted += summary.counters.nodes_created
        except FileNotFoundError:
            logging.error(f"File not found: {file_path}")
            raise
        except Exception as e:
            logging.error(f"Error during bulk insert for {table_name}: {e}")
            raise

        return total_inserted, total_lines
