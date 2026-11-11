"""Turn malformed client input into a 400 instead of a 500.

Request schemas keep many fields loose (``Any`` / ``dict``) so new upstream
features pass through. A wrong shape - an int where text is expected, a
string where a list is - then surfaces as ``TypeError`` / ``AttributeError``
deep in translation, and the endpoints report it as a server error. The
translation entry points re-raise those as :class:`InvalidRequestError`, a
``ValueError`` the endpoints already answer with 400.
"""

import functools
import inspect


class InvalidRequestError(ValueError):
    """The client's request has a shape the gateway cannot translate."""


_MALFORMED = (TypeError, AttributeError, KeyError, IndexError)


def reject_malformed(func):
    """Re-raise shape errors from a translation step as InvalidRequestError."""
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except _MALFORMED as e:
                raise InvalidRequestError(f"malformed request: {e}") from e

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except _MALFORMED as e:
            raise InvalidRequestError(f"malformed request: {e}") from e

    return wrapper
