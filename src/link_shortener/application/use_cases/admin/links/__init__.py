"""
Acts an operator takes on the link table as a whole.

Not on one link -- that is ``use_cases/links``, where a caller names a code
-- but on whatever rows match a rule: everything that has expired,
everything older than the retention window, the most recent few. They run
on a schedule or from the command line, and none of them takes a code.
"""
