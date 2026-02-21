"""SQLAlchemy engine, session factory, and DB initialisation."""

from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import settings

engine = create_engine(settings.database_url, echo=False, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

Base = declarative_base()


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Yield a transactional DB session and close it afterwards."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Create all tables defined on Base.metadata."""
    # Import models so they register with Base before create_all runs.
    import app.models.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    print("✔ Database tables created.")
