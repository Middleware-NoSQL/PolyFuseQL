from polyfuseql.strategy.Query import QueryStrategy
from sqlglot import exp


class SelectStrategy(QueryStrategy):
    async def execute(self, client, ast, backend):
        table = ast.find(exp.Table).name
        where_expr = ast.args.get("where").this
        # pk_col = where_expr.left.name # column will never be used?
        pk_val = where_expr.right.this
        conn = client.backends[backend]
        return [await conn.get(table, pk_val)]
