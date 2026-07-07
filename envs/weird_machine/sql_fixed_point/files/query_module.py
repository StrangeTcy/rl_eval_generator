class %%MODEL_CLASS%%:
    """
    Relational query generation engine.
    """
    def __init__(self):
        pass

    def get_reachability_query(self) -> str:
        """
        Return a single pure SQL query string that computes reachable pairs
        `(start, target)` from table `queries` over graph `edges(src, dst)`.
        """
        # Buggy initial implementation: only checks 1-hop direct edges
        return "SELECT q.start, q.target FROM queries q JOIN edges e ON q.start = e.src AND q.target = e.dst;"
