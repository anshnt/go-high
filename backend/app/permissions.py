"""The hook points of ADR 0004 (roles, record and field permissions). The record engine already calls these on every
list, read, write, association expansion and count, so the permission module only has to fill them in. Today everyone
in a workspace sees and may change every record."""
from .security import Ctx

EVERYTHING: dict = {"and": []}


def scope_filter(ctx: Ctx, obj) -> dict:
    """A filter AST (ADR 0002) of the records of `obj` that `ctx` may see. The engine ANDs it into every query."""
    return EVERYTHING


def redact(ctx: Ctx, obj, values: dict) -> dict:
    """`values` without the fields `ctx` may not read."""
    return values


def check_write(ctx: Ctx, obj, changes: dict) -> None:
    """Raises (403) when `changes` touches a hidden or read-only field of `obj`."""
