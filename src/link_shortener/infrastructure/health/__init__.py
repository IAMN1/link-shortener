"""
Asking every dependency whether it is answering.

What goes in is the probing itself: bounded, concurrent, and reporting a
timeout as its own state rather than as a refusal. A component that cannot
be reached within the budget is not the same as one that answered no, and
whatever asks must be able to tell them apart.
"""
