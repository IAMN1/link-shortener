"""
Proving who is calling, and looking up what they may do.

What goes in is the machinery behind an authentication or authorisation
port: the shape of a token and the reading of a role's permissions. Whether
a particular permission is enough for a particular act is a rule and belongs
to the domain -- this asks the question and carries the answer, and decides
neither.
"""
