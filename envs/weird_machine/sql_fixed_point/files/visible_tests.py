import sqlite3
from %%MODEL_FILE%% import %%MODEL_CLASS%%

def test_visible():
    engine = %%MODEL_CLASS%%()
    query = engine.get_reachability_query()
    
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.execute("CREATE TABLE edges (src INTEGER, dst INTEGER)")
    cur.execute("CREATE TABLE queries (start INTEGER, target INTEGER)")
    
    # Insert chain 1 -> 2 -> 3
    cur.executemany("INSERT INTO edges VALUES (?, ?)", [(1, 2), (2, 3)])
    # Queries: reachable (1, 3), (1, 2); unreachable (3, 1)
    cur.executemany("INSERT INTO queries VALUES (?, ?)", [(1, 3), (1, 2), (3, 1)])
    conn.commit()
    
    cur.execute(query)
    rows = set(cur.fetchall())
    expected = {(1, 2), (1, 3)}
    
    assert rows == expected, f"Expected reachable rows {expected}, got {rows}"
    print("Visible tests passed!")
    conn.close()

if __name__ == "__main__":
    test_visible()
