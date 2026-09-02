"""
Components that build use cases rather than infrastructure.

What goes in is the wiring for one group of use cases: the ports they need,
taken from the components beside them, handed to a constructor. The grouping
mirrors ``application/use_cases``, so a use case added there has one obvious
place to be built.
"""
