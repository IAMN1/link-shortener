"""
Building the reading of what the service has written.

Here rather than with the logging component because reading a journal and
writing one need different things: the reader is given the directory and the
file names, and never the handlers -- a deployment that writes nowhere still
has somewhere the journals would be, and must be able to answer that they
are empty.
"""
