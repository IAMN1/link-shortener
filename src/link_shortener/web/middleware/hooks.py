"""
Keeping a finished response finished.

An ``after_request`` hook runs when the work is already done: the status is
decided, the body is built, and what is left is a header, a cookie or a log
line. An exception there is not covered by any of the error handlers -- by
that point the response has left them behind -- so Flask falls through to
``handle_exception``, which re-raises when ``DEBUG`` or ``TESTING`` is on.
Under ``flask run --debug``, the documented way to run this service in
development, that is the interactive Werkzeug debugger: a full traceback,
local variables at every frame, and a console.

So the hooks are wrapped. A hook that fails loses whatever it was adding,
which is a header or an audit line, and the response the application
already produced goes out unchanged. The failure is logged, and logged as
an error, because a hook that raises is a bug even when nothing visible
comes of it.
"""

from functools import wraps


def response_hook(logger):
    """
    Build a decorator that stops an ``after_request`` hook from failing.

    Args:
        logger: Logger the failure is reported to.

    Returns:
        A decorator for a hook taking a response and returning one.
    """
    def decorate(hook):
        @wraps(hook)
        def guarded(response):
            try:
                return hook(response)
            except Exception as error:
                logger.error(
                    "Response hook failed",
                    hook=hook.__name__,
                    error=str(error),
                )
                return response
        return guarded
    return decorate
