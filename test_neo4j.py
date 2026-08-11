import sys
from neo4j import GraphDatabase

def verify_neo4j_state():
    uri = "bolt://polyfuseql-neo4j-graph:7687"
    user = "neo4j"
    password = "password"
    
    print("Connecting to Neo4j to verify database state...")
    try:
        driver = GraphDatabase.driver(uri, auth=(user, password))
        
        with driver.session() as session:
            print("\n--- Checking Nodes (Entities) ---")
            
            entities = ["Region", "Nation", "Part", "Supplier", "Customer", "Order", "LineItem", "PartSupp"]
            all_nodes_present = True
            
            for entity in entities:
                count = session.run(f"MATCH (n:{entity}) RETURN count(n) AS count").single()["count"]
                status = "✅ OK" if count > 0 else "❌ MISSING"
                print(f"{entity:<10} nodes: {count:<8} [{status}]")
                if count == 0:
                    all_nodes_present = False
            
            print("\n--- Checking Edges (Relationships) ---")
            
            edges = [
                ("Nation", "PART_OF", "Region"),
                ("Customer", "LOCATED_IN", "Nation"),
                ("Supplier", "LOCATED_IN", "Nation"),
                ("Order", "PLACED_BY", "Customer"),
                ("Supplier", "SUPPLIES", "Part"),
                ("Order", "CONTAINS", "Part")
            ]
            all_edges_present = True
            
            for source, rel, target in edges:
                count = session.run(f"MATCH (:{source})-[r:{rel}]->(:{target}) RETURN count(r) AS count").single()["count"]
                status = "✅ OK" if count > 0 else "❌ MISSING"
                print(f"(:{source})-[:{rel}]->(:{target}) edges: {count:<8} [{status}]")
                if count == 0:
                    all_edges_present = False

            print("\n--- Verification Result ---")
            if all_nodes_present and all_edges_present:
                print("🎉 SUCCESS! The database is fully loaded with both Nodes and Edges.")
                print("PolyFuseQL PySpark Connector will now be able to query LineItem and PartSupp natively!")
            else:
                print("⚠️ WARNING! Some nodes or edges are missing.")
                print("If LineItem or PartSupp are missing, you must run the neo4j-loader with the updated Cypher script.")
                
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        print("Make sure polyfuseql-neo4j-graph is running and accessible.")

if __name__ == "__main__":
    verify_neo4j_state()
