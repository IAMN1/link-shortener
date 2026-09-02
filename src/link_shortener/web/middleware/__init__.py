"""
What happens to every request, whichever route it is for.

What goes in is a concern that cannot belong to any one controller because
it applies before the route is known or after the answer is made:
establishing who is calling, refusing what is too frequent, compressing,
naming the policy a browser enforces, turning an exception into an envelope.

The test for membership is whether a controller could implement it without
the others having to remember to.
"""
