"""
The service as HTTP, and only as HTTP.

What goes in is code whose reason to exist is the protocol: routing, reading
a body, shaping an answer, the headers a browser is owed, the page a person
sees. Everything here holds a use case and calls it.

The rule that keeps the layer honest: nothing here decides anything a caller
using the CLI would have decided differently. A rule found in this directory
is a rule the other doors do not enforce.
"""
