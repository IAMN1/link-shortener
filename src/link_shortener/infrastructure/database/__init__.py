"""
The relational store, and everything that speaks to it.

What goes in is code that knows there is SQL underneath: the engine and its
pools, the mapped classes, the queries, the transaction boundary the
application opens without naming a database. Seeding is here too -- the
roles and permissions an empty schema is not usable without are as much a
part of the store as its tables.
"""
