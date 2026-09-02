"""
The shape of what crosses the wire, in both directions.

What goes in is a Pydantic model that validates a request body or describes
a response, and the document generated from them. A schema converts and
refuses shapes; it does not decide anything about the service -- a rule
spelled here as well as in the domain is a rule with two places to
disagree, and the field constraints that look like rules are declared from
the domain's own constants.
"""
