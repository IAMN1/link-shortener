"""
Ways of writing the application journal.

A member here implements ``Logger``: the levels a caller writes at, the
binding that carries context, and the health question that asks whether
this chain can still write anything at all.

That last one is answered by writing, which is why it is each
implementation's own and not a check made over them from outside: only the
implementation knows what its own write has to survive.
"""
