# scripts/seed_test_data.py
"""Peuple les bases de test avec des données factices. Idempotent : rejouable à volonté.

Les données sont déterministes (seed fixe) et contiennent des cas limites pour tester
le serveur MCP : jointures (INNER / LEFT / agrégats), valeurs NULL, accents, apostrophes,
clients sans commande, commandes de statuts variés, montants extrêmes.
"""
import random
from datetime import date, timedelta

from sqlalchemy import (
    Column, Date, ForeignKey, Integer, MetaData, String, Table, create_engine, func, insert, select,
)

from mcp_db_server.config import load_config

RNG = random.Random(42)

# Clients écrits à la main : cas limites volontaires.
HANDMADE_CUSTOMERS = [
    {"name": "Alice Dupont", "email": "alice@example.com", "city": "Lyon"},
    {"name": "Bruno Martin", "email": "bruno@example.com", "city": "Lille"},
    {"name": "Chloé Bernard", "email": "chloe@example.com", "city": "Nantes"},
    {"name": "Dylan O'Brien", "email": "dylan@example.com", "city": "Paris"},        # apostrophe (SQL)
    {"name": "Émilie Lefèvre", "email": "emilie@example.com", "city": "Lyon"},        # accents
    {"name": "François Müller", "email": "francois@example.com", "city": None},       # city NULL
    {"name": "Gaëlle Nguyen", "email": "gaelle@example.com", "city": "Paris"},        # sans commande
    {"name": "Hugo \"Le Roi\" Petit", "email": "hugo@example.com", "city": "Lille"},   # guillemets
    {"name": "Inès Garcia", "email": "ines@example.com", "city": "Marseille"},        # sans commande
    {"name": "Jean-Baptiste de la Tour-Maubourg", "email": "jb@example.com", "city": "Saint-Étienne"},
]

FIRST_NAMES = ["Léa", "Lucas", "Manon", "Nathan", "Camille", "Louis", "Sarah", "Thomas", "Julie", "Maxime",
               "Clara", "Antoine", "Zoé", "Paul", "Emma", "Hugo", "Jade", "Adam", "Lola", "Noah"]
LAST_NAMES = ["Moreau", "Simon", "Laurent", "Michel", "Garnier", "Faure", "Rousseau", "Blanc", "Guerin",
              "Muller", "Henry", "Roussel", "Nicolas", "Perrin", "Morin", "Mathieu", "Clement", "Gauthier"]
CITIES = ["Lyon", "Lille", "Nantes", "Paris", "Marseille", "Toulouse", "Bordeaux", "Strasbourg", None]
STATUSES = ["paid", "paid", "paid", "pending", "shipped", "cancelled", "refunded"]  # "paid" surpondéré
EXTRA_CUSTOMERS = 40
NO_ORDER_RATIO = 0.15   # part des clients générés sans aucune commande (pour les LEFT JOIN)


def build_customers() -> list[dict]:
    customers = list(HANDMADE_CUSTOMERS)
    for i in range(EXTRA_CUSTOMERS):
        first, last = RNG.choice(FIRST_NAMES), RNG.choice(LAST_NAMES)
        customers.append({
            "name": f"{first} {last}",
            "email": f"{first.lower()}.{last.lower()}{i}@example.com".replace("é", "e").replace("ë", "e"),
            "city": RNG.choice(CITIES),
        })
    for idx, customer in enumerate(customers, start=1):
        customer["id"] = idx
    return customers


def build_orders(customers: list[dict]) -> list[dict]:
    # Clients volontairement sans commande : Gaëlle et Inès + une fraction des clients générés.
    without_orders = {7, 9}
    without_orders |= {c["id"] for c in customers[len(HANDMADE_CUSTOMERS):] if RNG.random() < NO_ORDER_RATIO}

    start = date(2025, 1, 1)
    orders: list[dict] = []
    for customer in customers:
        if customer["id"] in without_orders:
            continue
        # Alice est une grosse cliente (agrégats / ORDER BY / LIMIT), les autres en ont 1 à 6.
        n_orders = 25 if customer["id"] == 1 else RNG.randint(1, 6)
        for _ in range(n_orders):
            orders.append({
                "customer_id": customer["id"],
                "amount_cents": RNG.choice([RNG.randint(99, 5_000), RNG.randint(5_000, 50_000)]),
                "status": RNG.choice(STATUSES),
                "ordered_at": start + timedelta(days=RNG.randint(0, 600)),
            })
    # Cas extrêmes : commande gratuite et très grosse commande.
    orders.append({"customer_id": 2, "amount_cents": 0, "status": "paid", "ordered_at": date(2025, 6, 1)})
    orders.append({"customer_id": 3, "amount_cents": 2_147_483_000, "status": "pending", "ordered_at": date(2026, 1, 1)})

    orders.sort(key=lambda o: o["ordered_at"])
    for idx, order in enumerate(orders, start=1):
        order["id"] = idx
    return orders


def build_schema(metadata: MetaData) -> tuple[Table, Table]:
    customers = Table(
        "customers", metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(100), nullable=False),
        Column("email", String(100), nullable=False, unique=True),
        Column("city", String(50)),
    )
    orders = Table(
        "orders", metadata,
        Column("id", Integer, primary_key=True),
        Column("customer_id", Integer, ForeignKey("customers.id"), nullable=False),
        Column("amount_cents", Integer, nullable=False),
        Column("status", String(20), nullable=False),
        Column("ordered_at", Date, nullable=False),
    )
    return customers, orders


def seed_connection(name: str, url: str) -> None:
    print(f"[{name}] connexion...")
    engine = create_engine(url)
    metadata = MetaData()
    customers, orders = build_schema(metadata)

    customer_rows = build_customers()
    order_rows = build_orders(customer_rows)

    with engine.begin() as conn:
        metadata.drop_all(conn)   # repart propre à chaque run, ordre FK géré automatiquement
        metadata.create_all(conn)
        conn.execute(insert(customers), customer_rows)
        conn.execute(insert(orders), order_rows)

        # Vérification rapide : INNER JOIN vs LEFT JOIN doivent différer (clients sans commande).
        inner = conn.scalar(
            select(func.count(func.distinct(customers.c.id))).select_from(customers.join(orders))
        )
        left_null = conn.scalar(
            select(func.count()).select_from(customers.outerjoin(orders)).where(orders.c.id.is_(None))
        )

    print(f"[{name}] {len(customer_rows)} clients, {len(order_rows)} commandes insérés "
          f"({inner} clients avec commande, {left_null} sans).")
    engine.dispose()


def main() -> None:
    config = load_config()
    for name, connection in config.connections.items():
        seed_connection(name, connection.url)


if __name__ == "__main__":
    main()
