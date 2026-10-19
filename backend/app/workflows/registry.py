"""What the graph and the actions share: time offsets, and the registry of actions. An action is a key, a pydantic
model for its config (which is also its JSON schema, for the builder, the API validator and the AI generator), and a
handler. Handlers register themselves in `actions`; nothing here imports them."""
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, Field

if TYPE_CHECKING:
    from .engine import Env

UNITS = {"minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}
MAX_OFFSET_SECONDS = 366 * 86400  # a wait or a due date more than a year out is a typo
Unit = Literal["minutes", "hours", "days", "weeks"]


def within_a_year(offset: dict) -> dict:
    if abs(seconds(offset)) > MAX_OFFSET_SECONDS:
        raise ValueError("is more than a year")
    return offset


# {"days": 2}: one unit and a whole number of it
Offset = Annotated[dict[Unit, Annotated[int, Field(ge=1, le=100000)]], Field(min_length=1, max_length=1),
                   AfterValidator(within_a_year)]
SignedOffset = Annotated[dict[Unit, Annotated[int, Field(ge=-100000, le=100000)]],
                         Field(min_length=1, max_length=1), AfterValidator(within_a_year)]


def seconds(offset: dict) -> int:
    (unit, count), = offset.items()
    return count * UNITS[unit]


class StepError(Exception):
    """A step that cannot do what it was asked: the message says why, in words a person can act on."""


MERGE = re.compile(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}")  # {{first_name}}: a field of the record, merged into text


def merge_keys(text: str) -> list[str]:
    return MERGE.findall(text)


@dataclass
class Out:
    """What a handler did: `input` is what it was asked to do (the rendered config), `output` what happened. `until`
    asks the engine to hold the run until then and run the node again (a send in quiet hours)."""
    input: dict = field(default_factory=dict)
    output: dict = field(default_factory=dict)
    until: Any = None


@dataclass
class Action:
    key: str
    label: str
    config: type[BaseModel]
    run: Callable[["Env", Any], Out]
    description: str = ""
    outbound: bool = False  # it leaves the system: through an outbox row with an idempotency key, never in the step
    refs: Callable[[Any], list[tuple[str, str]]] = lambda cfg: []  # (kind, id or key) of what the config uses
    check: Callable[..., dict[str, str]] | None = None  # (cat, obj, cfg) -> {path in the config: error}


ACTIONS: dict[str, Action] = {}


def action(key: str, label: str, config: type[BaseModel], *, description: str = "", outbound: bool = False,
           refs: Callable | None = None, check: Callable | None = None):
    """Registers the decorated handler as the action `key`."""
    def register(run):
        ACTIONS[key] = Action(key, label, config, run, description, outbound, refs or (lambda cfg: []), check)
        return run
    return register
