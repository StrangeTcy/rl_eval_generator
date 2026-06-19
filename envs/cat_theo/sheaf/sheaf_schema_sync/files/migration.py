import sqlite3

class %%MODEL_CLASS%%:
    def create_schema(self, db_path: str) -> None:
        # Establishes schema tables with circular dependencies.
        # Uses %%DEFER_CONSTRAINTS%% to toggle deferral of foreign keys.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            address_id INTEGER,
            FOREIGN KEY(address_id) REFERENCES addresses(id) %%DEFER_CONSTRAINTS%%
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY,
            user_id INTEGER,
            amount REAL,
            FOREIGN KEY(user_id) REFERENCES users(id) %%DEFER_CONSTRAINTS%%
        );
        """)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS addresses (
            id INTEGER PRIMARY KEY,
            transaction_id INTEGER,
            FOREIGN KEY(transaction_id) REFERENCES transactions(id) %%DEFER_CONSTRAINTS%%
        );
        """)
        conn.commit()
        conn.close()

    def insert_transaction(self, db_path: str, t_id: int, u_id: int, a_id: int, amount: float) -> None:
        # BUG: Naive insertion that fails under strict immediate circular foreign-key constraints.
        # This breaks when executing transactions over overlapping, circular table layouts.
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")
        
        cursor.execute("INSERT INTO addresses (id, transaction_id) VALUES (?, ?);", (a_id, t_id))
        cursor.execute("INSERT INTO users (id, address_id) VALUES (?, ?);", (u_id, a_id))
        cursor.execute("INSERT INTO transactions (id, user_id, amount) VALUES (?, ?, ?);", (t_id, u_id, amount))
        
        conn.commit()
        conn.close()
