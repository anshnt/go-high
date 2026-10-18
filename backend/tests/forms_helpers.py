"""Helpers of the forms tests: definition builders, and `Site`, one workspace's forms through the admin API plus the
public endpoints a visitor uses (an anonymous client with its own cookie jar, and an optional fake address)."""
from fastapi.testclient import TestClient

from app.main import app

H = "X-Workspace-Id"
PUBLIC = "/api/public/forms"


def form(*steps, logic_=None, **top) -> dict:
    return {"steps": list(steps), **({"logic": logic_} if logic_ is not None else {}), **top}


def step(key, *fields) -> dict:
    return {"key": key, "title": key.title(), "fields": list(fields)}


def q(key, type_="short_text", **extra) -> dict:
    return {"key": key, "type": type_, "label": key.replace("_", " ").title(), **extra}


def pick(*ids) -> dict:
    return {"options": [{"id": i, "label": i.title()} for i in ids]}


def lead(*extra) -> dict:
    """A one step lead form: name and email mapped to the contact, and any extra questions."""
    return form(step("s1", q("first_name", required=True, maps_to="first_name"),
                     q("email", "email", required=True, maps_to="email"), *extra))


def visitor(address: str | None = None) -> TestClient:
    return TestClient(app, client=(address, 50000)) if address else TestClient(app)


class Site:
    def __init__(self, client, ws: str, anonymous: TestClient | None = None):
        self.client, self.ws, self.anonymous = client, ws, anonymous or visitor()

    # the workspace member
    def create(self, name="Lead form", kind="form", definition=None, settings=None, **extra) -> dict:
        body = {"name": name, "kind": kind, **({"definition": definition} if definition else {}),
                **({"settings": settings} if settings else {}), **extra}
        r = self.client.post("/api/v1/forms", json=body, headers={H: self.ws})
        assert r.status_code == 201, r.text
        return r.json()

    def publish(self, f: dict, **body) -> dict:
        r = self.client.post(f"/api/v1/forms/{f['id']}/publish", json=body or None, headers={H: self.ws})
        assert r.status_code == 200, r.text
        return r.json()

    def live(self, definition=None, settings=None, **kw) -> dict:
        return self.publish(self.create(definition=definition or lead(), settings=settings, **kw))

    def save(self, f: dict, definition: dict) -> dict:
        r = self.client.post(f"/api/v1/forms/{f['id']}/versions", json={"definition": definition},
                             headers={H: self.ws})
        assert r.status_code == 200, r.text
        return r.json()

    def get(self, path: str, **params):
        return self.client.get(f"/api/v1/{path}", params=params, headers={H: self.ws})

    def records(self, object_key="contact", **params) -> list[dict]:
        r = self.get(f"objects/{object_key}/records", limit=200, **params)
        assert r.status_code == 200, r.text
        return r.json()["data"]

    # the visitor
    def page(self, key: str):
        return self.anonymous.get(f"{PUBLIC}/{key}")

    def view(self, key: str) -> str:
        r = self.anonymous.post(f"{PUBLIC}/{key}/views")
        assert r.status_code == 200, r.text
        return r.json()["view_token"]

    def start(self, key: str, answers=None, token="view", **extra):
        body = {"answers": answers or {}, **extra}
        if token == "view":
            body["view_token"] = self.view(key)
        elif token:
            body["view_token"] = token
        return self.anonymous.post(f"{PUBLIC}/{key}/submissions", json=body)

    def finish(self, key: str, started: dict, answers=None, token="view", **extra):
        body = {"answers": answers or {}, "resume_token": started["resume_token"], **extra}
        if token == "view":
            body["view_token"] = self.view(key)
        elif token:
            body["view_token"] = token
        return self.anonymous.post(f"{PUBLIC}/{key}/submissions/{started['id']}/complete", json=body)

    def submit(self, f: dict, answers: dict, expect: int = 200, **extra) -> dict:
        """What a visitor's browser does: view the page, start a response, complete it."""
        key = f["public_key"]
        started = self.start(key, {}, **{k: v for k, v in extra.items() if k in ("url", "referrer", "utm")})
        assert started.status_code == 201, started.text
        r = self.finish(key, started.json(), answers, **{k: v for k, v in extra.items() if k == "hp"})
        assert r.status_code == expect, r.text
        return r.json()
