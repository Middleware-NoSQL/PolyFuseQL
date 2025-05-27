# 📋 Backlog de Historias de Usuario – Middleware de Persistencia Políglota

---

## 🟢 Historias Realizadas

### **1. Connect to PostgreSQL, Redis, Neo4j – *Done***
- `feat(connector): Postgres ping/count/get`
- `feat(connector): Redis ping/count/get`
- `feat(connector): Neo4j ping/count/get`
- `test: connectivity + count + get`

### **2. Stack runs in CI – *Done***
- `infra: compose-action workflow`

## 🛠 Historias Iniciales

### **3. Add sqlglot dependency**
- `infra: poetry add sqlglot`

### **4. PolyClient.query() – SELECT * WHERE pk**
- `feat(core): implement query() routing`
- `feat(core): extend mapping lookup function`
- `test: query returns customer row (depends on 5)`

### **5. Test: query customer (Redis)**

### **6. Test: query product (Postgres)**

### **7. Test: query customer node (Neo4j)**

### **8. Docs: README query examples**

## 🧠 Historias Estratégicas según Plan de Tesis

### **9. docs: systematic literature review on polyglot middleware**

### **10. docs: middleware requirements gathering**

### **11. design: architecture modules definition (parser, optimizer, engine)**

### **12. feat(core): basic optimizer for routing**

### **13. feat(core): extend parser for WHERE/ORDER/GROUP**

## 🧩 Historias Funcionales por Compatibilidad SQL

### **14. Others – INSERT**
- `feat(pg): support `INSERT``
- `test(pg): query using `INSERT``
- `feat(redis): support `INSERT` via string/hash/json`
- `test(redis): query `INSERT` with sample`
- `feat(neo4j): support `INSERT``
- `test(neo4j): cypher using `INSERT``

### **15. Others – UPDATE**
- `feat(pg): support `UPDATE``
- `test(pg): query using `UPDATE``
- `feat(redis): support `UPDATE` via string/hash/json`
- `test(redis): query `UPDATE` with sample`
- `feat(neo4j): support `UPDATE``
- `test(neo4j): cypher using `UPDATE``

### **16. Others – DELETE**
- `feat(pg): support `DELETE``
- `test(pg): query using `DELETE``
- `feat(redis): support `DELETE` via string/hash/json`
- `test(redis): query `DELETE` with sample`
- `feat(neo4j): support `DELETE``
- `test(neo4j): cypher using `DELETE``

### **17. Alias – AS**
- `feat(pg): support `AS``
- `test(pg): query using `AS``
- `feat(neo4j): support `AS``
- `test(neo4j): cypher using `AS``

### **18. WHERE – AND, OR, NOT**
- `feat(pg): support `AND, OR, NOT``
- `test(pg): query using `AND, OR, NOT``
- `feat(neo4j): support `AND, OR, NOT``
- `test(neo4j): cypher using `AND, OR, NOT``

### **19. WHERE – =, >, <, >=, <=, <>**
- `feat(pg): support `=, >, <, >=, <=, <>``
- `test(pg): query using `=, >, <, >=, <=, <>``
- `feat(neo4j): support `=, >, <, >=, <=, <>``
- `test(neo4j): cypher using `=, >, <, >=, <=, <>``

### **20. WHERE – IN**
- `feat(pg): support `IN``
- `test(pg): query using `IN``
- `feat(redis): support `IN` via string/hash/json`
- `test(redis): query `IN` with sample`
- `feat(neo4j): support `IN``
- `test(neo4j): cypher using `IN``

### **21. WHERE – LIKE**
- `feat(pg): support `LIKE``
- `test(pg): query using `LIKE``
- `feat(redis): support `LIKE` via string/hash/json`
- `test(redis): query `LIKE` with sample`
- `feat(neo4j): support `LIKE``
- `test(neo4j): cypher using `LIKE``

### **22. WHERE – BETWEEN**
- `feat(pg): support `BETWEEN``
- `test(pg): query using `BETWEEN``
- `feat(neo4j): support `BETWEEN``
- `test(neo4j): cypher using `BETWEEN``

### **23. Group by – Having**
- `feat(pg): support `Having``
- `test(pg): query using `Having``
- `feat(neo4j): support `Having``
- `test(neo4j): cypher using `Having``

### **24. Others – CREATE**
- `feat(pg): support `CREATE``
- `test(pg): query using `CREATE``
- `feat(redis): support `CREATE` via string/hash/json`
- `test(redis): query `CREATE` with sample`
- `feat(neo4j): support `CREATE``
- `test(neo4j): cypher using `CREATE``

### **25. Others – DROP**
- `feat(pg): support `DROP``
- `test(pg): query using `DROP``
- `feat(redis): support `DROP` via string/hash/json`
- `test(redis): query `DROP` with sample`
- `feat(neo4j): support `DROP``
- `test(neo4j): cypher using `DROP``

### **26. Others – ALTER**
- `feat(pg): support `ALTER``
- `test(pg): query using `ALTER``
- `feat(neo4j): support `ALTER``
- `test(neo4j): cypher using `ALTER``

### **27. Others – TRUNCATE**
- `feat(pg): support `TRUNCATE``
- `test(pg): query using `TRUNCATE``
- `feat(redis): support `TRUNCATE` via string/hash/json`
- `test(redis): query `TRUNCATE` with sample`
- `feat(neo4j): support `TRUNCATE``
- `test(neo4j): cypher using `TRUNCATE``

### **28. Others – COMMIT**
- `feat(pg): support `COMMIT``
- `test(pg): query using `COMMIT``
- `feat(neo4j): support `COMMIT``
- `test(neo4j): cypher using `COMMIT``

### **29. Others – ROLLBACK**
- `feat(pg): support `ROLLBACK``
- `test(pg): query using `ROLLBACK``
- `feat(neo4j): support `ROLLBACK``
- `test(neo4j): cypher using `ROLLBACK``

### **30. Others – COALESE**
- `feat(pg): support `COALESE``
- `test(pg): query using `COALESE``

### **31. WHERE – EXISTS**
- `feat(pg): support `EXISTS``
- `test(pg): query using `EXISTS``
- `feat(neo4j): support `EXISTS``
- `test(neo4j): cypher using `EXISTS``

### **32. WHERE – ALL**
- `feat(pg): support `ALL``
- `test(pg): query using `ALL``
- `feat(neo4j): support `ALL``
- `test(neo4j): cypher using `ALL``

### **33. WHERE – ANY**
- `feat(pg): support `ANY``
- `test(pg): query using `ANY``
- `feat(neo4j): support `ANY``
- `test(neo4j): cypher using `ANY``

### **34. Others – GRANT**
- `feat(pg): support `GRANT``
- `test(pg): query using `GRANT``
- `feat(neo4j): support `GRANT``
- `test(neo4j): cypher using `GRANT``

### **35. Others – REVOKE**
- `feat(pg): support `REVOKE``
- `test(pg): query using `REVOKE``
- `feat(neo4j): support `REVOKE``
- `test(neo4j): cypher using `REVOKE``

### **36. Others – RENAME**
- `feat(pg): support `RENAME``
- `test(pg): query using `RENAME``
- `feat(neo4j): support `RENAME``
- `test(neo4j): cypher using `RENAME``

### **37. FUNCTIONS – MAX()**
- `feat(pg): support `MAX()``
- `test(pg): query using `MAX()``
- `feat(redis): support `MAX()` via string/hash/json`
- `test(redis): query `MAX()` with sample`
- `feat(neo4j): support `MAX()``
- `test(neo4j): cypher using `MAX()``

### **38. FUNCTIONS – MIN()**
- `feat(pg): support `MIN()``
- `test(pg): query using `MIN()``
- `feat(redis): support `MIN()` via string/hash/json`
- `test(redis): query `MIN()` with sample`
- `feat(neo4j): support `MIN()``
- `test(neo4j): cypher using `MIN()``

### **39. FUNCTIONS – COUNT()**
- `feat(pg): support `COUNT()``
- `test(pg): query using `COUNT()``
- `feat(redis): support `COUNT()` via string/hash/json`
- `test(redis): query `COUNT()` with sample`
- `feat(neo4j): support `COUNT()``
- `test(neo4j): cypher using `COUNT()``

### **40. FUNCTIONS – SUM()**
- `feat(pg): support `SUM()``
- `test(pg): query using `SUM()``
- `feat(redis): support `SUM()` via string/hash/json`
- `test(redis): query `SUM()` with sample`
- `feat(neo4j): support `SUM()``
- `test(neo4j): cypher using `SUM()``

### **41. FUNCTIONS – AVG()**
- `feat(pg): support `AVG()``
- `test(pg): query using `AVG()``
- `feat(redis): support `AVG()` via string/hash/json`
- `test(redis): query `AVG()` with sample`
- `feat(neo4j): support `AVG()``
- `test(neo4j): cypher using `AVG()``

### **42. JOINS – Full JOIN**
- `feat(pg): support `Full JOIN``
- `test(pg): query using `Full JOIN``

### **43. JOINS – Right JOIN**
- `feat(pg): support `Right JOIN``
- `test(pg): query using `Right JOIN``

### **44. JOINS – Left JOIN**
- `feat(pg): support `Left JOIN``
- `test(pg): query using `Left JOIN``
- `feat(neo4j): support `Left JOIN``
- `test(neo4j): cypher using `Left JOIN``

### **45. JOINS – Inner Join**
- `feat(pg): support `Inner Join``
- `test(pg): query using `Inner Join``
- `feat(neo4j): support `Inner Join``
- `test(neo4j): cypher using `Inner Join``

### **46. Order by – Order by DESC**
- `feat(pg): support `Order by DESC``
- `test(pg): query using `Order by DESC``
- `feat(neo4j): support `Order by DESC``
- `test(neo4j): cypher using `Order by DESC``

### **47. Order by – Order by ASC**
- `feat(pg): support `Order by ASC``
- `test(pg): query using `Order by ASC``
- `feat(neo4j): support `Order by ASC``
- `test(neo4j): cypher using `Order by ASC``

### **48. Group by – Group by Column**
- `feat(pg): support `Group by Column``
- `test(pg): query using `Group by Column``
- `feat(neo4j): support `Group by Column``
- `test(neo4j): cypher using `Group by Column``