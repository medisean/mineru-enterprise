from app.core.database import Base
from app.models.models import *  # noqa: ensure all models are registered with Base

target_metadata = Base.metadata
