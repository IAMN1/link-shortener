"""
What a command does, with nothing in it about being a command.

A body here is handed what it needs, does the work, and returns the result
-- a line to report, a count, an entity. It prints nothing and exits
nothing: what an operator sees is settled one layer out, so a body stays
answerable by its return value rather than by its output.

That is the whole of the rule. A function that would have to name click, a
stream or an exit code to do its job belongs in ``adapters`` instead.
"""
