"""
Plan seed data — used to populate product_plans for new products.
The live source of truth is the product_plans DB table; this file is only
referenced when seeding via POST /dashboard/plans/seed/{product_slug}.
"""
from dataclasses import dataclass, field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


@dataclass
class PlanSeed:
    slug: str
    display_name: str
    default_seats: int
    max_seats: int | None
    features: list[str] = field(default_factory=list)
    sort_order: int = 0


SEED_PLANS: dict[str, list[PlanSeed]] = {
    "zenmsp": [
        PlanSeed("starter",      "Starter",      1,  5,    ["basic"],                                                              0),
        PlanSeed("professional", "Professional", 5,  25,   ["basic", "ms365", "contracts", "multi_currency"],                      1),
        PlanSeed("enterprise",   "Enterprise",   25, None, ["basic", "ms365", "contracts", "multi_currency", "quotes", "custom_fields"], 2),
    ],
    "zenssl": [
        PlanSeed("starter",      "Starter",      1, None, ["basic", "ssl_monitor"],                                               0),
        PlanSeed("professional", "Professional", 1, None, ["basic", "ssl_monitor", "bulk_renew", "notifications"],                1),
        PlanSeed("enterprise",   "Enterprise",   1, None, ["basic", "ssl_monitor", "bulk_renew", "notifications", "api_access", "white_label"], 2),
    ],
    "imapsync-gui": [
        PlanSeed("starter",      "Starter",      1, None, ["basic", "local_sync"],                                                0),
        PlanSeed("professional", "Professional", 1, None, ["basic", "local_sync", "scheduled_sync", "multi_account"],             1),
        PlanSeed("enterprise",   "Enterprise",   1, None, ["basic", "local_sync", "scheduled_sync", "multi_account", "api_access", "priority_support"], 2),
    ],
    "_default": [
        PlanSeed("starter",      "Starter",      1,  5,    ["basic"], 0),
        PlanSeed("professional", "Professional", 5,  25,   ["basic"], 1),
        PlanSeed("enterprise",   "Enterprise",   25, None, ["basic"], 2),
    ],
}


def get_seeds(product_slug: str) -> list[PlanSeed]:
    return SEED_PLANS.get(product_slug) or SEED_PLANS["_default"]


async def fetch_features(db: AsyncSession, product_slug: str, plan_slug: str) -> list[str]:
    """Primary features lookup — queries the DB. Falls back to seed data if no DB plan exists."""
    from .models import ProductPlan, Product
    stmt = (
        select(ProductPlan)
        .join(Product, ProductPlan.product_id == Product.id)
        .where(Product.slug == product_slug, ProductPlan.slug == plan_slug)
    )
    result = await db.execute(stmt)
    plan = result.scalar_one_or_none()
    if plan is not None:
        return plan.features or []
    # Fallback to seed data for products not yet configured in dashboard
    seed = next((s for s in get_seeds(product_slug) if s.slug == plan_slug), None)
    return seed.features if seed else []
