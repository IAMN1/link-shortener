"""
Reading a journal on behalf of a caller entitled to read that one.

The reading itself is a port; what belongs here is the decision about
whether the caller may be told. It is a directory of its own rather than a
member of ``admin`` because the entitlement is not an administrator's: the
journals answer to ``logs:view`` and ``audit:view``, which an operator
managing accounts need not hold.
"""
