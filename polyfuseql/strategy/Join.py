from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class JoinStrategy(QueryStrategy):
    """Strategy to handle queries containing JOIN clauses."""

    async def execute(
        self, client, ast: exp.Select, backend: str, use_catalogue: bool
    ):  # noqa: F501
        if not backend:
            msg = "An 'engine' must be specified for JOIN operations."
            raise ValueError(msg)

        conn = client.backends.get(backend)
        if not conn:
            raise ValueError(f"Connector for backend '{backend}' not found.")

        # Delegate the entire join logic to the specific connector
        return await conn.join(ast)
