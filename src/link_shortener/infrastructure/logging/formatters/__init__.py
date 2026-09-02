"""
How one record becomes one line of text.

A formatter here is handed a standard-library ``LogRecord`` and returns the
string that lands in a file or on a terminal. The structlog chain dresses
its records through processors of its own, so nothing for it comes here.

What is settled in this directory is shape and never destination: which
fields appear and how they are spelled, not which file the line goes into
or whether it goes anywhere at all.
"""
