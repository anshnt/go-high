"""What a calendar's settings may hold: request bodies for the admin API, and the checks on questions and locations that
the public page relies on."""
import re
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, field_validator

from . import slots

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=60)]
Kind = Literal["personal", "round_robin", "collective", "class", "service"]
KEY = re.compile(r"^[a-z][a-z0-9_]{0,29}$")
BUILT_IN = {"name": "text", "email": "email", "phone": "phone"}
DEFAULT_QUESTIONS = [{"key": "name", "label": "Name", "type": "text", "required": True, "options": []},
                     {"key": "email", "label": "Email", "type": "email", "required": True, "options": []},
                     {"key": "phone", "label": "Phone", "type": "phone", "required": True, "options": []}]


def zone(value: str) -> str:
    slots.zone(value)  # raises ValueError, which pydantic reports against the field
    return value


def check_durations(values: list[int]) -> list[int]:
    if not 1 <= len(values) <= 3 or len(set(values)) != len(values) or any(not 5 <= v <= 480 for v in values):
        raise ValueError("one to three different lengths, each 5 to 480 minutes")
    return values


def check_reminders(values: list[int]) -> list[int]:
    if len(values) > 5 or any(not 5 <= v <= 60 * 24 * 14 for v in values):
        raise ValueError("up to 5 reminders, each between 5 minutes and 14 days before")
    return sorted(set(values), reverse=True)


Zone = Annotated[str, AfterValidator(zone)]
Durations = Annotated[list[int], AfterValidator(check_durations)]
Reminders = Annotated[list[int], AfterValidator(check_reminders)]


def hyphenate(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "calendar"


class Location(BaseModel):
    kind: Literal["phone", "video", "in_person", "custom"]
    value: Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)] = ""

    @field_validator("value")
    @classmethod
    def link(cls, value: str, info) -> str:
        if info.data.get("kind") == "video" and value and not re.match(r"^https?://\S+$", value):
            raise ValueError("a video location is a web link")
        return value


class Question(BaseModel):
    key: str
    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    type: Literal["text", "long_text", "select", "email", "phone"] = "text"
    required: bool = False
    options: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]] = []


def check_questions(questions: list[Question]) -> None:
    """Name and email are always asked, phone is asked and may be optional, and up to 10 questions of your own."""
    keys = [q.key for q in questions]
    if len(set(keys)) != len(keys):
        raise ValueError("each question needs its own key")
    if not {"name", "email", "phone"} <= set(keys):
        raise ValueError("name, email and phone are always asked")
    custom = 0
    for q in questions:
        if q.key in BUILT_IN:
            if q.type != BUILT_IN[q.key] or (q.key != "phone" and not q.required):
                raise ValueError(f"{q.key} is a {BUILT_IN[q.key]} question, and name and email are required")
            continue
        custom += 1
        if not KEY.match(q.key):
            raise ValueError(f"{q.key!r} is not a valid key (lower case letters, digits and _)")
        if q.type in ("email", "phone"):
            raise ValueError("your own questions are text, long text or select")
        if q.type == "select" and not 2 <= len(q.options) <= 20:
            raise ValueError("a select question needs 2 to 20 options")
    if custom > 10:
        raise ValueError("at most 10 questions of your own")


def question_rows(questions: list[Question]) -> list[dict]:
    return [q.model_dump() | ({} if q.type == "select" else {"options": []}) for q in questions]


class Settings(BaseModel):
    """The settings of a calendar, all optional here so PATCH can send some; creating fills in defaults."""
    name: Name | None = None
    slug: Slug | None = None
    description: Annotated[str, StringConstraints(max_length=2000)] | None = None
    kind: Kind | None = None
    durations: Durations | None = None
    buffer_before: Annotated[int, Field(ge=0, le=240)] | None = None
    buffer_after: Annotated[int, Field(ge=0, le=240)] | None = None
    min_notice: Annotated[int, Field(ge=0, le=43200)] | None = None
    window_days: Annotated[int, Field(ge=1, le=365)] | None = None
    slot_interval: Annotated[int, Field(ge=5, le=240)] | None = None
    max_per_day: Annotated[int, Field(ge=1, le=1000)] | None = None
    seats: Annotated[int, Field(ge=1, le=1000)] | None = None
    time_zone: Zone | None = None
    locations: Annotated[list[Location], Field(max_length=5)] | None = None
    questions: list[Question] | None = None
    confirmation: Literal["auto", "manual"] | None = None
    color: Annotated[str, StringConstraints(pattern=r"^[a-z]{3,12}$")] | None = None
    status: Literal["active", "paused", "archived"] | None = None
    reminders: Reminders | None = None
    cutoff_hours: Annotated[int, Field(ge=0, le=24 * 60)] | None = None

    @field_validator("questions")
    @classmethod
    def asked(cls, value):
        if value is not None:
            check_questions(value)
        return value


class HostIn(BaseModel):
    user_id: uuid.UUID
    weight: Annotated[int, Field(ge=0, le=100)] = 1
    priority: Annotated[int, Field(ge=-100, le=100)] = 0
    daily_cap: Annotated[int, Field(ge=1, le=1000)] | None = None
    active: bool = True


class ResourceIn(BaseModel):
    name: Name
    kind: Literal["room", "equipment"] = "room"
    quantity: Annotated[int, Field(ge=1, le=1000)] = 1


class ResourcePatch(BaseModel):
    name: Name | None = None
    kind: Literal["room", "equipment"] | None = None
    quantity: Annotated[int, Field(ge=1, le=1000)] | None = None
