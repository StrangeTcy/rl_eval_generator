import os
from migration import %%MODEL_CLASS%%

def test_migration_creation():
    db_path = "test_visible.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    mig = %%MODEL_CLASS%%()
    mig.create_schema(db_path)
    assert os.path.exists(db_path)
    os.remove(db_path)
