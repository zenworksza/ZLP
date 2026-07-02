import os
from unittest.mock import patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from authority.app.models import Base, Product, LicenseKey
from authority.app.database import get_db

TEST_DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://zlp:zlp@localhost:5432/zlp_test",
)

test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool, echo=False)
test_session_maker = async_sessionmaker(test_engine, class_=AsyncSession, expire_on_commit=False)


async def override_get_db():
    async with test_session_maker() as session:
        yield session


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    try:
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        pytest.skip(f"Cannot connect to test database: {exc}")
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await test_engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def truncate_tables(setup_database):
    yield
    async with test_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest_asyncio.fixture
async def client(setup_database):
    # Import the app after setup so overrides are in place.
    import authority.app.main as app_module
    import authority.app.database as db_module

    app_module.app.dependency_overrides[get_db] = override_get_db

    # Patch scheduler functions so they're no-ops during tests, and redirect
    # the lifespan's engine.begin() to the test engine so it doesn't require
    # a production database connection.
    with patch.dict(os.environ, {"DASHBOARD_TOKEN": "test-token"}), \
         patch.object(app_module, "start_scheduler", lambda: None), \
         patch.object(app_module, "stop_scheduler", lambda: None), \
         patch.object(db_module, "engine", test_engine):
        async with AsyncClient(
            transport=ASGITransport(app=app_module.app),
            base_url="http://test",
        ) as ac:
            yield ac


@pytest_asyncio.fixture
async def seed_db(setup_database):
    async with test_session_maker() as session:
        product = Product(name="ZenMSP", slug="zenmsp")
        session.add(product)
        await session.flush()

        license_key = LicenseKey(
            product_id=product.id,
            key="ZLP-TEST-1234-ABCD",
            plan="professional",
            seats=5,
            status="active",
        )
        session.add(license_key)
        await session.commit()
        await session.refresh(product)
        await session.refresh(license_key)

    return {"product": product, "license_key": license_key}
