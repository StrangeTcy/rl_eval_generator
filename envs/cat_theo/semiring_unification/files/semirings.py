class %%ARITH_CLASS%%:
    zero = 0.0
    one = 1.0

    @staticmethod
    def add(x: float, y: float) -> float:
        return x + y

    @staticmethod
    def mul(x: float, y: float) -> float:
        return x * y

class %%TROP_CLASS%%:
    # BUG: Incorrect identities and operations for Min-Plus (Tropical) semiring.
    # zero should be infinity, one should be 0.0, and mul(x, y) should be x + y.
    zero = 0.0
    one = 1.0

    @staticmethod
    def add(x: float, y: float) -> float:
        return min(x, y)

    @staticmethod
    def mul(x: float, y: float) -> float:
        return x * y

class %%BOOL_CLASS%%:
    # BUG: Incorrect identity elements for Boolean semiring.
    # zero should be False, one should be True.
    zero = True
    one = False

    @staticmethod
    def add(x: bool, y: bool) -> bool:
        return x or y

    @staticmethod
    def mul(x: bool, y: bool) -> bool:
        return x and y
