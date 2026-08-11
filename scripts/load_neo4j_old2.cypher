// =============================================================================
// PHASE 0: WIPE DATABASE & SCHEMA SETUP
// =============================================================================

// Clear the database completely
MATCH (n) DETACH DELETE n;

// Establish Constraints & Identifiers to prevent deadlock and massive DB locks
CREATE CONSTRAINT FOR (r:Region) REQUIRE r.r_regionkey IS UNIQUE;
CREATE CONSTRAINT FOR (n:Nation) REQUIRE n.n_nationkey IS UNIQUE;
CREATE CONSTRAINT FOR (p:Part) REQUIRE p.p_partkey IS UNIQUE;
CREATE CONSTRAINT FOR (s:Supplier) REQUIRE s.s_suppkey IS UNIQUE;
CREATE CONSTRAINT FOR (c:Customer) REQUIRE c.c_custkey IS UNIQUE;
CREATE CONSTRAINT FOR (o:Order) REQUIRE o.o_orderkey IS UNIQUE;

// Composite Keys
CREATE INDEX FOR (ps:PartSupp) ON (ps.ps_partkey, ps.ps_suppkey);
CREATE INDEX FOR (l:LineItem) ON (l.l_orderkey, l.l_linenumber);

// =============================================================================
// PHASE 1: NODE INGESTION (Base Entities & Join Entities)
// =============================================================================

// --- Region ---
LOAD CSV FROM 'file:///tpch-data/region.tbl' AS line FIELDTERMINATOR '|'
MERGE (:Region {
r_regionkey: toInteger(line[0]),
r_name: line[1],
r_comment: line[2]
});

// --- Nation ---
LOAD CSV FROM 'file:///tpch-data/nation.tbl' AS line FIELDTERMINATOR '|'
MERGE (:Nation {
n_nationkey: toInteger(line[0]),
n_name: line[1],
n_regionkey: toInteger(line[2]),
n_comment: line[3]
});

// --- Part ---
LOAD CSV FROM 'file:///tpch-data/part.tbl' AS line FIELDTERMINATOR '|'
MERGE (:Part {
p_partkey: toInteger(line[0]),
p_name: line[1],
p_mfgr: line[2],
p_brand: line[3],
p_type: line[4],
p_size: toInteger(line[5]),
p_container: line[6],
p_retailprice: toFloat(line[7]),
p_comment: line[8]
});

// --- Supplier ---
LOAD CSV FROM 'file:///tpch-data/supplier.tbl' AS line FIELDTERMINATOR '|'
MERGE (:Supplier {
s_suppkey: toInteger(line[0]),
s_name: line[1],
s_address: line[2],
s_nationkey: toInteger(line[3]),
s_phone: line[4],
s_acctbal: toFloat(line[5]),
s_comment: line[6]
});

// --- Customer ---
LOAD CSV FROM 'file:///tpch-data/customer.tbl' AS line FIELDTERMINATOR '|'
MERGE (:Customer {
c_custkey: toInteger(line[0]),
c_name: line[1],
c_address: line[2],
c_nationkey: toInteger(line[3]),
c_phone: line[4],
c_acctbal: toFloat(line[5]),
c_mktsegment: line[6],
c_comment: line[7]
});

// --- Order ---
LOAD CSV FROM 'file:///tpch-data/orders.tbl' AS line FIELDTERMINATOR '|'
MERGE (:Order {
o_orderkey: toInteger(line[0]),
o_custkey: toInteger(line[1]),
o_orderstatus: line[2],
o_totalprice: toFloat(line[3]),
o_orderdate: line[4],
o_orderpriority: line[5],
o_clerk: line[6],
o_shippriority: toInteger(line[7]),
o_comment: line[8]
});

// --- PartSupp (Must be nodes for PolyFuseQL SQL mapping) ---
LOAD CSV FROM 'file:///tpch-data/partsupp.tbl' AS line FIELDTERMINATOR '|'
MERGE (:PartSupp {
    ps_partkey: toInteger(line[0]),
    ps_suppkey: toInteger(line[1]),
    ps_availqty: toInteger(line[2]),
    ps_supplycost: toFloat(line[3]),
    ps_comment: line[4]
});

// --- LineItem (Must be nodes for PolyFuseQL SQL mapping) ---
LOAD CSV FROM 'file:///tpch-data/lineitem.tbl' AS line FIELDTERMINATOR '|'
MERGE (:LineItem {
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
});

// =============================================================================
// PHASE 2: RELATIONSHIP MAPPING & EDGE INGESTION
// =============================================================================

// --- 2.1 Tie Nations to Regions ---
MATCH (n:Nation), (r:Region)
WHERE n.n_regionkey = r.r_regionkey
MERGE (n)-[:PART_OF]->(r);

// --- 2.2 Tie Customers to Nations ---
MATCH (c:Customer), (n:Nation)
WHERE c.c_nationkey = n.n_nationkey
MERGE (c)-[:LOCATED_IN]->(n);

// --- 2.3 Tie Suppliers to Nations ---
MATCH (s:Supplier), (n:Nation)
WHERE s.s_nationkey = n.n_nationkey
MERGE (s)-[:LOCATED_IN]->(n);

// --- 2.4 Tie Orders to Customers ---
MATCH (o:Order), (c:Customer)
WHERE o.o_custkey = c.c_custkey
MERGE (o)-[:PLACED_BY]->(c);

// --- 2.5 Ingest PartSupp as Relational Edges ---
// In Neo4j, a join table like PartSupp is often best represented as an edge.
// We match the Part and Supplier nodes, then inject the relationship properties.
LOAD CSV FROM 'file:///tpch-data/partsupp.tbl' AS line FIELDTERMINATOR '|'
MATCH (p:Part {p_partkey: toInteger(line[0])})
MATCH (s:Supplier {s_suppkey: toInteger(line[1])})
MERGE (s)-[:SUPPLIES {
availqty: toInteger(line[2]),
supplycost: toFloat(line[3]),
comment: line[4]
}]->(p);

// --- 2.6 Ingest LineItem as Relational Edges ---
// The LineItem connects Orders to the Parts supplied by Suppliers.
// We map the edge from the Order directly to the Part, containing line details.
LOAD CSV FROM 'file:///tpch-data/lineitem.tbl' AS line FIELDTERMINATOR '|'
MATCH (o:Order {o_orderkey: toInteger(line[0])})
MATCH (p:Part {p_partkey: toInteger(line[1])})
MERGE (o)-[:CONTAINS {
suppkey: toInteger(line[2]),
linenumber: toInteger(line[3]),
quantity: toFloat(line[4]),
extendedprice: toFloat(line[5]),
discount: toFloat(line[6]),
tax: toFloat(line[7]),
returnflag: line[8],
linestatus: line[9],
shipdate: line[10],
commitdate: line[11],
receiptdate: line[12],
shipinstruct: line[13],
shipmode: line[14],
comment: line[15]
}]->(p);

