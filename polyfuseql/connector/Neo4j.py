# ruff: noqa: F401
import logging
import os
from typing import Dict, Any, Optional, List
from polyfuseql.connector.Connector import Connector
from polyfuseql.utils.tpch_schema import TPCH_SCHEMA
from neo4j import AsyncGraphDatabase as AGD, AsyncDriver
from polyfuseql.utils.utils import env
from sqlglot import exp


class Neo4jConnector(Connector):
    """Connector for Neo4j with persistent connection handling."""

    async def get_all(self, entity: str) -> List[Dict[str, Any]]:
        pass

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
            logging.info("Neo4j-con-get-cypher", cypher)
            logging.info("Neo4j-con-get-pk_val", pk_val)
            logging.info("Neo4j-con-get-pk_val-type", type(pk_val))
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
            # The "+=" operator efficiently merges properties
            # from the payload map
            cypher = f"MATCH (n:{label} {{`{pk_col}`: $pk_val}}) "
            cypher += "SET n += $payload"
            summary = await s.run(cypher, pk_val=pk_val, payload=payload)
            return 1 if summary else 0

    async def join(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Manually translates a SQL JOIN AST to a Cypher query."""
        driver = self._get_driver()

        # 1. Deconstruct the AST
        left_table_expr = ast.args.get("from").this
        join_expr = ast.args.get("joins")[0]
        right_table_expr = join_expr.this
        on_condition = join_expr.args.get("on")

        left_table_name = left_table_expr.this.name.capitalize()
        left_alias = left_table_expr.alias_or_name
        right_table_name = right_table_expr.this.name.capitalize()
        right_alias = right_table_expr.alias_or_name

        # 2. Build the MATCH clause
        match_clause = f"MATCH ({left_alias}:{left_table_name}), "
        match_clause += f"({right_alias}:{right_table_name})"
        # 3. Build the WHERE clause
        on_left = f"{on_condition.this.table}.{on_condition.this.this.name}"
        on_right = f"{on_condition.expression.table}"
        on_right += f".{on_condition.expression.this.name}"
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

        # 5. Build the RETURN clause
        return_expressions = []
        for col_expr in ast.expressions:
            col_name = col_expr.this.name
            table_alias = col_expr.table
            return_alias = f"`{col_name}`"
            return_expressions.append(
                f"{table_alias}.{col_name} AS {return_alias}"
            )  # noqa: F501

        return_clause_str = "RETURN " + ", ".join(return_expressions)

        # 6. Assemble the final Cypher Query
        cypher_query = f"{match_clause}{where_clause_str} {return_clause_str}"
        logging.info(f"Manually constructed Cypher query: {cypher_query}")
        logging.info("Neo4j-join-cypher-query", cypher_query)
        # 7. Execute and return results
        async with driver.session() as s:
            result = await s.run(cypher_query, **params)
            # FIX: Use an async list comprehension
            # to correctly iterate the AsyncResult
            return [dict(record) async for record in result]

    async def group_by(self, ast: exp.Select) -> List[Dict[str, Any]]:
        """Manually translates a SQL GROUP BY to a Cypher aggregation query."""
        driver = self._get_driver()

        # 1. Deconstruct the AST
        table_name = ast.find(exp.Table).name.capitalize()
        match_clause = f"MATCH (n:{table_name})"

        # 2. Build the RETURN clause from the
        # GROUP BY and aggregation expressions
        return_expressions = []
        for expr in ast.expressions:
            logging.info("============================")
            logging.info("neo4j-group-by-expr", expr)
            logging.info("neo4j-group-by-expr-instance", type(expr))
            logging.info("============================")
            if isinstance(expr, exp.Alias) and str(expr).lower().startswith(
                "count"
            ):  # noqa: F501
                # It's an aggregation function,
                # e.g., COUNT(*) AS customer_count
                alias = expr.alias_or_name
                return_expressions.append(f"count(n) AS {alias}")
            elif isinstance(expr, exp.Column):
                # It's a grouping key, e.g., "country"
                col_name = expr.this.name
                return_expressions.append(f"n.{col_name} AS {col_name}")

        if not return_expressions:
            raise ValueError(
                "GROUP BY query must have columns or aggregations in SELECT."
            )

        return_clause = "RETURN " + ", ".join(return_expressions)

        # 3. Assemble and run the query
        cypher_query = f"{match_clause} {return_clause}"
        msg = f"neo4j-Manually constructed GROUP BY query: {cypher_query}"
        logging.info(msg)

        async with driver.session() as s:
            result = await s.run(cypher_query)
            return [dict(record) async for record in result]

    async def bulk_insert(self, table_name: str, file_path: str) -> int:
        """
        Performs a high-performance bulk insert using Neo4j's LOAD CSV command.
        """
        driver = self._get_driver()
        schema = TPCH_SCHEMA.get(table_name.lower())
        if not schema:
            raise ValueError(f"No schema definition found for table: {table_name}")

        columns = schema["columns"]
        label = table_name.capitalize()
        file_name = os.path.basename(file_path)

        # Construct the SET clause for the Cypher query
        set_clauses = [f"n.{col} = row[{i}]" for i, col in enumerate(columns)]
        set_clause_str = ", ".join(set_clauses)

        # Construct the full LOAD CSV query
        cypher_query = f"""
        LOAD CSV FROM 'file:///{file_name}' AS row FIELDTERMINATOR '|'
        CREATE (n:{label})
        SET {set_clause_str}
        """

        async with driver.session() as s:
            summary = await s.run(cypher_query)
            return summary.counters.nodes_created
