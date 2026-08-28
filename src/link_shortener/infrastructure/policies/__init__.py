"""
Implementations of the domain's ways of computing a value.

What goes in is one class answering a domain port whose whole job is
arithmetic on a value -- how a short code is generated, how a URL is
reduced to a hash. The domain names what is wanted and what it must
guarantee; the choice of algorithm is here, where changing it costs nothing
above.
"""
