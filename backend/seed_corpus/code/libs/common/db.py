'''Database session handling shared by the services.'''

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .config import BaseSettings


def engine_for(config: BaseSettings) -> Engine:
    return create_engine(config.database_url, pool_pre_ping=True)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    '''Commit on success, roll back on failure, always close.'''
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
