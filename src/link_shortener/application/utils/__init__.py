"""
Pure functions and value builders more than one use case needs.

Something goes here when it takes values and returns values: no unit of
work, no port, no I/O of any kind, and nothing it could not compute from its
arguments. That is what makes these safe to call from anywhere in the layer
and testable without a fixture.

Work that needs a transaction is a service, in ``application/services``,
even when several use cases share it.
"""
