from alembic import context

from app import api, events, jobs, models, webhooks  # noqa: F401  (registers tables on Base.metadata)
from app.calendars import models as calendar_models  # noqa: F401
from app.db import Base, engine
from app.forms import models as form_models  # noqa: F401
from app.inbox import models as inbox_models  # noqa: F401
from app.notifications import models as notification_models  # noqa: F401
from app.records import models as record_models  # noqa: F401
from app.tasks import models as task_models  # noqa: F401
from app.usage import models as usage_models  # noqa: F401
from app.workflows import models as workflow_models  # noqa: F401

target_metadata = Base.metadata

with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()
