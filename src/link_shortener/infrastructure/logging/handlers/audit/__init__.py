"""
Ways of writing the audit trail.

A member here implements ``AuditLogger``: handed an event and its fields,
it writes one record. The wrapper that counts what it is told before
passing it on qualifies on the same terms -- it answers the port, so it can
stand wherever the others stand, which is what lets counting be wired in
without a caller knowing.

Masking belongs to this side rather than to the caller. An address or a URL
is made safe on its way into the record, so no caller can be the one that
forgot.
"""
