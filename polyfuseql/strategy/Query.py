class QueryStrategy:
    async def execute(self, client, ast, backend):
        raise NotImplementedError
