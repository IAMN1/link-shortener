"""
The interfaces for writing a record, one per journal with its own vocabulary.

The application log takes a message and whatever fields the caller thought
worth binding. The audit trail takes an event from a fixed enum, because it
is read by filtering on that field, and a free-form string there is a record
nobody finds again. That difference is why these are separate ports and
not one with a flag.
"""
