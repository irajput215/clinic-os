import logging

from sqlmodel import Session

from app.core.config import settings
from app.core.db import engine, init_db
from app.modules.identity_tenancy.service import seed_demo_tenant

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init() -> None:
    with Session(engine) as session:
        init_db(session)
        # Opt-in: the demo organisation is MVP seed data, not deployment behaviour.
        if settings.SEED_DEMO_TENANT:
            seed_demo_tenant(session)


def main() -> None:
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
