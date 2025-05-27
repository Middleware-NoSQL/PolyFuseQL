# PolyFuseQL · Universal Query Orchestrator

PolyFuseQL es un middleware escrito en **Python 3.12** que unifica
consultas **SQL** y **NoSQL** mediante un único endpoint REST/GraphQL
basado en FastAPI. Permite enchufar conectores (plugins) para motores
heterogéneos (PostgreSQL, MongoDB, Cassandra, …) manteniendo la sintaxis
SQL estándar.

![CI](https://github.com/<TU-USUARIO>/polyfuseql/actions/workflows/ci.yml/badge.svg)

## Características

- 🌐 **API unificada**: traduce SQL a dialectos nativos o delega a módulos
  externos vía REST.
- 🧪 **Test-Driven Development**: 100 % de endpoints cubiertos por pruebas
  unitarias y de contrato.
- 🔌 **Arquitectura plugin**: `ConnectorPlugin` para añadir motores en
  caliente (`pip install polyfuseql-redis`).
- 🚀 **Rendimiento**: asincronía con Uvicorn + optimizador rule-based.

## Instalación (dev)

```bash
git clone https://github.com/<TU-USUARIO>/polyfuseql.git
cd polyfuseql
poetry install
uvicorn app.main:app --reload
```
### Datos de ejemplo

PolyFuseQL descarga en tiempo de ejecución los ficheros Northwind de:
- https://github.com/harryho/db-samples (JSON)  
- https://github.com/neo4j-graph-examples/northwind (Cypher)

No redistribuimos esos archivos; solo se usan para pruebas locales.

---
## Ejemplos de consultas
### 1· Búsqueda transparente en una sola tienda
```python
from polyfuseql.client.PolyClient import PolyClient
import asyncio

async def demo():
  pc = PolyClient()
  rows = await pc.query("SELECT * FROM customers WHERE customerId = 'ALFKI'")
  print(rows[0]["companyName"]) # -> Alfreds Futterkiste

asyncio.run(demo())
```
`PolyFuseQL` enruta la consulta al backend propietario (Redis, por defecto) basándose en el catálogo interno.

### 2· Distribución a múltiples backends
```python
rows = await pc.query(
  "SELECT * FROM customers WHERE customerId = 'ALFKI'",
  engines=["redis", "postgres", "neo4j"],
  include_source=True,
  )
for r in rows:
    print(r["_source"], r["companyName"])
```
Resultado:
```
redis Alfreds Futterkiste
postgres Alfreds Futterkiste
neo4j Alfreds Futterkiste
```
Use el indicador `include_source` solo cuando necesite la procedencia; de lo contrario, la API devuelve filas de entidad sin formato.

### 3 · Manejo de SQL no compatible
```python
try:
    await pc.query("SELECT name FROM customers")
except NotImplementedError:
    print("Solo `SELECT * … WHERE pk` es compatible con MVP")
```

Para más detalles, consulte la [Historia de usuario n.° 4](../../issues/4) y la implementación en `polyfuseql/client/PolyClient.py`.