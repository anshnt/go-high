from alembic import context

from app import api, events, jobs, models, webhooks  # noqa: F401  (registers tables on Base.metadata)
from app.db import Base, engine
from app.records import models as record_models  # noqa: F401

target_metadata = Base.metadata

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
