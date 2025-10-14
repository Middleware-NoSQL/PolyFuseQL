class QueryStrategy:
    async def execute(self, client, ast, backend, use_catalogue):
        raise NotImplementedError
