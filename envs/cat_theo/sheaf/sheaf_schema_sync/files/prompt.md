# Microservice Schema Integration

Your task is to implement a unified, globally consistent database schema migration in `migration.py`.

In distributed microservices, individual services maintain localized, overlapping database schemas representing their specific "views" of the global database entities. 

The task is to complete the `%%MODEL_CLASS%%` class in `migration.py` to construct a single unified SQLite database schema. It must:
1. Support local schema definitions for Service A (Billing), Service B (Shipping), and Service C (Marketing) individually.
2. Allow inserting and querying data over pairwise overlapping segments of these services.
3. Be robust under global cascading operations (avoiding transactional foreign-key constraint deadlocks during bulk insertions where circular dependency loops are triggered).

The current implementation in `migration.py` runs, but violates global consistency during concurrent, circular multi-table inserts. Correct the schema definition and transaction ordering to ensure the global migration is structurally sound.
