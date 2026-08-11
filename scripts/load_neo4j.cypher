// -----------------------------------------------------------------------------
// 0. SCHEMA SETUP (Constraints & Indexes)
// -----------------------------------------------------------------------------
// We create constraints to ensure data integrity.

CREATE CONSTRAINT IF NOT EXISTS FOR (r:Region) REQUIRE r.r_regionkey IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (n:Nation) REQUIRE n.n_nationkey IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (p:Part) REQUIRE p.p_partkey IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (s:Supplier) REQUIRE s.s_suppkey IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (c:Customer) REQUIRE c.c_custkey IS UNIQUE;
CREATE CONSTRAINT IF NOT EXISTS FOR (o:Order) REQUIRE o.o_orderkey IS UNIQUE;

// Composite Keys (Community Edition uses Indexes for performance)
CREATE INDEX IF NOT EXISTS FOR (ps:PartSupp) ON (ps.ps_partkey, ps.ps_suppkey);
CREATE INDEX IF NOT EXISTS FOR (l:LineItem) ON (l.l_orderkey, l.l_linenumber);


// 0.5. CLEANUP PREVIOUS PARTIAL LOADS
// -----------------------------------------------------------------------------
// Because we use CREATE instead of MERGE for speed, we MUST ensure the DB is empty first.
MATCH (n) CALL { WITH n DETACH DELETE n } IN TRANSACTIONS OF 50000 ROWS;
// -----------------------------------------------------------------------------


// -----------------------------------------------------------------------------
// 1. BULK LOAD (Optimized with APOC and CREATE)
// -----------------------------------------------------------------------------

// Region
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/region.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:Region {
    r_regionkey: toInteger(line[0]),
    r_name: line[1],
    r_comment: line[2]
  })",
  {batchSize: 50000, parallel: true}
);

// Nation
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/nation.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:Nation {
    n_nationkey: toInteger(line[0]),
    n_name: line[1],
    n_regionkey: toInteger(line[2]),
    n_comment: line[3]
  })",
  {batchSize: 50000, parallel: true}
);

// Part
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/part.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:Part {
    p_partkey: toInteger(line[0]),
    p_name: line[1],
    p_mfgr: line[2],
    p_brand: line[3],
    p_type: line[4],
    p_size: toInteger(line[5]),
    p_container: line[6],
    p_retailprice: toFloat(line[7]),
    p_comment: line[8]
  })",
  {batchSize: 50000, parallel: true}
);

// Supplier
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/supplier.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:Supplier {
    s_suppkey: toInteger(line[0]),
    s_name: line[1],
    s_address: line[2],
    s_nationkey: toInteger(line[3]),
    s_phone: line[4],
    s_acctbal: toFloat(line[5]),
    s_comment: line[6]
  })",
  {batchSize: 50000, parallel: true}
);

// PartSupp
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/partsupp.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:PartSupp {
    ps_partkey: toInteger(line[0]),
    ps_suppkey: toInteger(line[1]),
    ps_availqty: toInteger(line[2]),
    ps_supplycost: toFloat(line[3]),
    ps_comment: line[4]
  })",
  {batchSize: 50000, parallel: true}
);

// Customer
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/customer.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:Customer {
    c_custkey: toInteger(line[0]),
    c_name: line[1],
    c_address: line[2],
    c_nationkey: toInteger(line[3]),
    c_phone: line[4],
    c_acctbal: toFloat(line[5]),
    c_mktsegment: line[6],
    c_comment: line[7]
  })",
  {batchSize: 50000, parallel: true}
);

// Orders
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/orders.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:Order {
    o_orderkey: toInteger(line[0]),
    o_custkey: toInteger(line[1]),
    o_orderstatus: line[2],
    o_totalprice: toFloat(line[3]),
    o_orderdate: line[4],
    o_orderpriority: line[5],
    o_clerk: line[6],
    o_shippriority: toInteger(line[7]),
    o_comment: line[8]
  })",
  {batchSize: 50000, parallel: true}
);

// LineItem
CALL apoc.periodic.iterate(
  "LOAD CSV FROM 'file:///tpch-data/lineitem.tbl' AS line FIELDTERMINATOR '|' RETURN line",
  "CREATE (:LineItem {
    l_orderkey: toInteger(line[0]),
    l_partkey: toInteger(line[1]),
    l_suppkey: toInteger(line[2]),
    l_linenumber: toInteger(line[3]),
    l_quantity: toFloat(line[4]),
    l_extendedprice: toFloat(line[5]),
    l_discount: toFloat(line[6]),
    l_tax: toFloat(line[7]),
    l_returnflag: line[8],
    l_linestatus: line[9],
    l_shipdate: line[10],
    l_commitdate: line[11],
    l_receiptdate: line[12],
    l_shipinstruct: line[13],
    l_shipmode: line[14],
    l_comment: line[15]
  })",
  {batchSize: 50000, parallel: true}
);
