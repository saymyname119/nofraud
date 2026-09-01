import pytest
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

# Override settings before app is imported
import os
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///test.db"

from app.main import app
from app.audit.models import Base
from app.database import get_session
from app.scoring.model import init_model

# Test Database Engine
engine = create_async_engine(
    "sqlite+aiosqlite:///test.db",
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False
)

async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestingSessionLocal() as session:
        yield session

app.dependency_overrides[get_session] = override_get_session


@pytest.fixture(autouse=True)
async def setup_db():
    """Create fresh tables and init model for every test."""
    init_model("ml/artifact/model.pkl", "ml/artifact/version.json")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a session for test functions to directly interact with DB."""
    async with TestingSessionLocal() as session:
        yield session

@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """Provide an HTTP client that talks directly to the ASGI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), 
        base_url="http://test"
    ) as ac:
        yield ac
