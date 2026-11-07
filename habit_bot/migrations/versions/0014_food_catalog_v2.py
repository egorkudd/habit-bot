"""Новый базовый каталог еды (правки 1.0.2): старые продукты каталога и их копии у пользователей удаляются,
новые копируются тем, у кого были базовые продукты из анкеты. Записи еды не меняются (значения в них — копии).

Revision ID: 0014_food_catalog_v2
Revises: 0013_chat_messages
Create Date: 2026-11-07
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0014_food_catalog_v2"
down_revision = "0013_chat_messages"
branch_labels = None
depends_on = None

REMOVED = ("chicken_thigh", "chicken_cooked", "pasta_boiled", "protein_30g", "chickenburger_rostics",
           "chef_basket_rostics", "nuggets_vit", "ham_toast_vit", "fresh_muffin_vit", "pelmeni")
KEPT = ("buckwheat_pack", "banana")
# (ключ, название, единица, ккал, белки, жиры, углеводы) — как в habit_bot/modules/food/catalog.py
ADDED = (
    ("chicken_fillet", "Куриное филе", "100g", 113, 23.6, 1.9, 0.4),
    ("cottage_cheese_5", "Творог 5%", "100g", 121, 17.2, 5, 1.8),
    ("rice_pack", "Рис сухой (пакет 80 г)", "piece", 275.2, 5.36, 0.56, 63.12),
    ("potato", "Картофель", "100g", 77, 2, 0.4, 16.3),
)

food_item = sa.table(
    "food_item", sa.column("id", sa.Integer()), sa.column("user_id", sa.Integer()),
    sa.column("catalog_key", sa.String()), sa.column("name", sa.String()), sa.column("kind", sa.String()),
    sa.column("composition", sa.Text()), sa.column("unit", sa.String()), sa.column("portion_label", sa.String()),
    sa.column("kcal", sa.Float()), sa.column("protein", sa.Float()), sa.column("fat", sa.Float()),
    sa.column("carbs", sa.Float()), sa.column("price", sa.Float()), sa.column("active", sa.Boolean()),
    sa.column("source_catalog_id", sa.Integer()), sa.column("public_id", sa.Uuid()),
    sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()), sa.column("version", sa.Integer()),
)
food_entry = sa.table("food_entry", sa.column("food_item_id", sa.Integer()))


def _row(**values: object) -> dict[str, object]:
    now = datetime.now(UTC).replace(tzinfo=None)
    return {"kind": "product", "composition": "", "portion_label": None, "price": None, "active": True,
            "public_id": uuid.uuid4(), "created_at": now, "updated_at": now, "version": 1, **values}


def _drop(conn: sa.Connection, ids: list[int]) -> None:
    if ids:
        conn.execute(food_entry.update().where(food_entry.c.food_item_id.in_(ids)).values(food_item_id=None))
        conn.execute(food_item.delete().where(food_item.c.id.in_(ids)))


def upgrade() -> None:
    conn = op.get_bind()
    catalog = {key: id_ for id_, key in conn.execute(
        sa.select(food_item.c.id, food_item.c.catalog_key).where(food_item.c.catalog_key.is_not(None)))}
    owners = sorted({u for (u,) in conn.execute(sa.select(food_item.c.user_id).where(
        food_item.c.source_catalog_id.in_(list(catalog.values())), food_item.c.user_id.is_not(None)).distinct())})
    removed = [catalog[k] for k in REMOVED if k in catalog]
    copies = [i for (i,) in conn.execute(sa.select(food_item.c.id).where(food_item.c.source_catalog_id.in_(removed)))]
    _drop(conn, copies)
    _drop(conn, removed)
    for key, name, unit, kcal, protein, fat, carbs in ADDED:
        source = catalog.get(key)
        if source is None:
            source = conn.execute(food_item.insert().values(_row(
                user_id=None, catalog_key=key, name=name, unit=unit, kcal=kcal, protein=protein, fat=fat,
                carbs=carbs, source_catalog_id=None)).returning(food_item.c.id)).scalar_one()
        have = {u for (u,) in conn.execute(sa.select(food_item.c.user_id).where(
            food_item.c.source_catalog_id == source))}
        rows = [_row(user_id=u, catalog_key=None, name=name, unit=unit, kcal=kcal, protein=protein, fat=fat,
                     carbs=carbs, source_catalog_id=source) for u in owners if u not in have]
        if rows:
            conn.execute(food_item.insert(), rows)


def downgrade() -> None:
    """Старый набор не возвращается (его загрузит прежняя версия при старте); убираются только новые продукты."""
    conn = op.get_bind()
    added = [i for (i,) in conn.execute(sa.select(food_item.c.id).where(
        food_item.c.catalog_key.in_([a[0] for a in ADDED])))]
    copies = [i for (i,) in conn.execute(sa.select(food_item.c.id).where(food_item.c.source_catalog_id.in_(added)))]
    _drop(conn, copies)
    _drop(conn, added)
