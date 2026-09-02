"""
One act the service performs, per module, whatever surface asks for it.

A use case owns the whole of one thing a caller can ask for: it opens its
own unit of work, applies the rules, writes what has to be written and
records what has to be recorded. That is what makes the HTTP API, the
dashboard and the command line able to ask for the same act and get the
same answer, including the same refusals.

The subdirectories group them by what the act is about. Work several use
cases share goes to ``application/services``; work that only one of them
does stays inside it.

``base_use_case.py`` is not an act. It holds what every use case inherits:
the loggers bound to the request, and the reading of a short code.
"""
