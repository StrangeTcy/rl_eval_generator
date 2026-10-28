"""Only invoke inside an authorized isolated runner."""

from .session import Session

Session().run()
