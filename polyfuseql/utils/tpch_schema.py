# polyfuseql/utils/tpch_schema.py (New File)
# Central repository for TPC-H table schemas.
# This provides a single source of truth for column names and primary keys,
# which is essential for schema-aware operations like bulk loading.

TPCH_SCHEMA = {
    "region": {
        "columns": ["r_regionkey", "r_name", "r_comment"],
        "pk": "r_regionkey",
    },
    "nation": {
        "columns": ["n_nationkey", "n_name", "n_regionkey", "n_comment"],
        "pk": "n_nationkey",
    },
    "part": {
        "columns": [
            "p_partkey",
            "p_name",
            "p_mfgr",
            "p_brand",
            "p_type",
            "p_size",
            "p_container",
            "p_retailprice",
            "p_comment",
        ],
        "pk": "p_partkey",
    },
    "supplier": {
        "columns": [
            "s_suppkey",
            "s_name",
            "s_address",
            "s_nationkey",
            "s_phone",
            "s_acctbal",
            "s_comment",
        ],
        "pk": "s_suppkey",
    },
    "partsupp": {
        "columns": [
            "ps_partkey",
            "ps_suppkey",
            "ps_availqty",
            "ps_supplycost",
            "ps_comment",
        ],
        # Composite primary key
        "pk": ["ps_partkey", "ps_suppkey"],
    },
    "customer": {
        "columns": [
            "c_custkey",
            "c_name",
            "c_address",
            "c_nationkey",
            "c_phone",
            "c_acctbal",
            "c_mktsegment",
            "c_comment",
        ],
        "pk": "c_custkey",
    },
    "orders": {
        "columns": [
            "o_orderkey",
            "o_custkey",
            "o_orderstatus",
            "o_totalprice",
            "o_orderdate",
            "o_orderpriority",
            "o_clerk",
            "o_shippriority",
            "o_comment",
        ],
        "pk": "o_orderkey",
    },
    "lineitem": {
        "columns": [
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "l_quantity",
            "l_extendedprice",
            "l_discount",
            "l_tax",
            "l_returnflag",
            "l_linestatus",
            "l_shipdate",
            "l_commitdate",
            "l_receiptdate",
            "l_shipinstruct",
            "l_shipmode",
            "l_comment",
        ],
        # Composite primary key
        "pk": ["l_orderkey", "l_linenumber"],
    },
}

TPCH_TABLE_ORDER = [
    "region",
    "nation",
    "supplier",
    "customer",
    "part",
    "partsupp",
    "orders",
    "lineitem",
]
