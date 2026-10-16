"""The record engine (ADR 0002): contacts, companies, deals and custom objects share one table, one field validator,
one filter language and one API."""
from .types import validate

__all__ = ["validate"]  # `records.validate(field, value)`: the one place a value is checked for its field
