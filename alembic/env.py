from logging.config import fileConfig
import os

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.config import get_settings
from backend.database import Base
from backend import models  # noqa: F401
from backend import deploy_models  # noqa: F401
from backend import dispatch_models  # noqa: F401
from backend import evolution_models  # noqa: F401
from backend import orchestrator_models  # noqa: F401
from backend import release_models  # noqa: F401
from backend import review_models  # noqa: F401
from backend.alpha_workflow import models as alpha_workflow_models  # noqa: F401
from backend.agent_runtime import models as agent_runtime_models  # noqa: F401
from backend.agent_runtime.executors.computer.actions import models as computer_action_models  # noqa: F401
from backend.agent_runtime.executors.computer import models as computer_executor_models  # noqa: F401
from backend.agent_runtime.workflows.computer import models as computer_workflow_models  # noqa: F401
from backend.device_center import models as device_center_models  # noqa: F401
from backend.ai_capabilities import models as ai_capability_models  # noqa: F401
from backend.brain_execution import models as brain_execution_models  # noqa: F401
from backend.brain_orchestrator import models as brain_orchestrator_models  # noqa: F401
from backend.brain_tool_router import models as brain_tool_router_models  # noqa: F401
from backend.employee_execution import models as employee_execution_models  # noqa: F401
from backend.knowledge_center import models as knowledge_center_models  # noqa: F401
from backend.observability import models as observability_models  # noqa: F401
from backend.research_runtime import models as research_runtime_models  # noqa: F401
from backend.skills_engine import models as skills_engine_models  # noqa: F401
from backend.tool_center import models as tool_center_models  # noqa: F401
from backend.tool_router import models as tool_router_models  # noqa: F401


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
config.set_main_option("sqlalchemy.url", os.getenv("DATABASE_URL", get_settings().DATABASE_URL))
_skip_sqlite_drift = os.getenv("ALEMBIC_SKIP_SQLITE_DRIFT") == "1"


def _include_object(obj, name, type_, reflected, compare_to):
    if _skip_sqlite_drift:
        return False
    return True


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(config.get_section(config.config_ini_section), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=_include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
