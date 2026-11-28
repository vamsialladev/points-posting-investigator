"""Read-only evidence: what the rules baseline and the investigator may look at, and how they cite it (RFC-0002).

Everything here only reads. The database access goes through the `*_investigator` roles (SELECT only, read-only
transactions) and the Kafka access through the `investigator` login (describe and read only), so the read-only
guarantee is enforced by Postgres and by the broker, not by this code.

Every item read is an `Evidence` with a stable `id`. A claim cites those ids. Free text inside an item (a log line,
an error detail, a correlation ID) is data written by other systems or people: it is carried in fields named in
`model.UNTRUSTED`, cut to a fixed length, and is never an instruction to whoever reads it.
"""
