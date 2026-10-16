from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_engine(request: Request) -> AsyncEngine:
    """The application engine, or 503 when the database is not configured."""
    engine: AsyncEngine | None = getattr(request.app.state, "engine", None)
    if engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="database is not configured",
        )
    return engine


def get_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    """A session factory over the app engine; 503 before it when there is no DB."""
    return async_sessionmaker(get_engine(request), expire_on_commit=False)


EngineDep = Annotated[AsyncEngine, Depends(get_engine)]
SessionFactoryDep = Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)]
