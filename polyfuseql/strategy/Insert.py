from polyfuseql.strategy.Query import QueryStrategy


class InsertStrategy(QueryStrategy):
    async def execute(self, client, ast, backend):
        table = ast.this.name
        columns = [col.name for col in ast.expressions]
        values = [val.this for val in ast.args["expressions"][0].expressions]
        payload = dict(zip(columns, values))
        conn = client.backends[backend]
        return await conn.insert(table, payload)
