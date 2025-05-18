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
