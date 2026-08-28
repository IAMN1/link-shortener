"""
Acts that put data into the service rather than change what is there.

Seeding is the only one: it fills an empty deployment with links so that a
page has something to show. It goes through the ordinary creation path
rather than writing rows, which is why it is a use case and not a script.
"""
