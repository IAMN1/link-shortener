"""
The batch endpoint, and the steps it is divided into.

Only ``batch_create_links.py`` is an act a caller can ask for. The rest are
its stages -- reading the input into groups, looking up what already exists,
minting codes for the remainder, building the response -- separated because
one transaction's worth of work is too much for one module to hold, not
because anything else needs them. The container builds them and hands them
to the use case; nothing else calls a method on one.
"""
