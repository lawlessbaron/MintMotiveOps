"""One-off (idempotent) import — Alibaba stock purchases, Sep 2026.

Run once against the target database:

    python3 scripts/import_2026_09_alibaba_stock.py

Locally this uses the same SQLite instance/ the app itself uses. Against
production, run it from a Render Shell session on the web service (same
private network as the Postgres instance — DATABASE_URL is already set
there, same as when the app itself boots); this script has no network
access to the production DB from anywhere else.

Idempotent: safe to re-run. Each Part is matched/skipped by its
part_number, each Supplier by supplier_name, and each shipment's Purchase
Order by a stable marker at the start of its notes field — so re-running
after a partial failure, or after adding a new shipment to SHIPMENTS
below, never double-creates anything already there.

What a shipment does after creation depends on its "received" flag:
  - received=True  (goods already in hand): lines are marked fully
    received (bumps parts.quantity_on_hand, auto-files the GST expense
    via the same path Purchase Orders > Receive uses), then landed cost
    (the shipment's freight) is applied — folded into each part's
    moving-average unit_cost, same as the real "Apply Landed Cost" button.
  - received=False (still in transit): the PO and its lines are created
    and freight is recorded, but nothing is marked received and no landed
    cost is applied yet — quantity_on_hand stays 0. Once the shipment
    physically arrives, either receive it normally through Purchase
    Orders in the app, or just flip this shipment's received flag to
    True here and re-run the script — it detects the PO already exists
    and receives/lands it in place rather than re-creating anything,
    which is how Pro Micro and the wire went from False to True below.

Known gap: expense_date on the auto-filed GST expenses defaults to
whenever this script is actually run (today), not the real order date —
exact order dates weren't available for these. If any of these shipments
need to land in a specific BAS period, adjust the expense date under
Administration/Financial > Expenses after running this.

Still missing entirely (no price/qty/photos given yet) — add a new
SHIPMENTS entry once that lands: RP2040 Pico, DuPont jumper cables,
MT3608 booster board, 1N4148 diodes (one bundled order, $11.22 shipping
total — noted here so it isn't lost, but nothing was created for it).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from app.db import get_db, generate_number, receive_po_line, apply_landed_cost, now_str

# Real "Sold by" company confirmed via an Alibaba order-detail screenshot.
# Where it wasn't (most of these — order pages weren't screenshotted), we
# do NOT invent a company name: everything routes through this single,
# clearly-labeled placeholder, with the real product listing recorded on
# each part_suppliers.source_url so the actual storefront can be looked up
# and the supplier corrected later.
UNCONFIRMED_SUPPLIER = "Alibaba Seller — TBC"
UNCONFIRMED_SUPPLIER_NOTES = (
    "Placeholder — the actual Alibaba storefront/company name wasn't confirmed "
    "for these purchases (no \"Sold by\" screenshot). Each part's Suppliers tab "
    "has the real product listing URL; look up the true selling company there "
    "and either rename this supplier or split it out, then repoint the parts."
)

SHIPMENTS = [
    {
        "marker": "[ALIBABA-IMPORT] Toowei waterproof toggle switches",
        "supplier_name": UNCONFIRMED_SUPPLIER,
        "supplier_notes": UNCONFIRMED_SUPPLIER_NOTES,
        "source_url": "https://www.alibaba.com/product-detail/Toowei-Waterproof-SPST-SPDT-on-OFF_1601682026159.html",
        "received": True,
        "shipping_usd": 54.18,
        "parts": [
            dict(part_number="ALI-T501AT", part_name="Toowei T501AT Waterproof Toggle Switch (ON-OFF)",
                 qty=5, unit_cost=2.19),
            dict(part_number="ALI-T501BT", part_name="Toowei T501BT Waterproof Toggle Switch (ON-ON)",
                 qty=5, unit_cost=2.38),
            dict(part_number="ALI-T501CT", part_name="Toowei T501CT Waterproof Toggle Switch (ON-OFF-ON)",
                 qty=5, unit_cost=2.53),
            dict(part_number="ALI-T501FT", part_name="Toowei T501FT Waterproof Toggle Switch ((ON)-OFF)",
                 qty=5, unit_cost=2.98),
            dict(part_number="ALI-T501MT", part_name="Toowei T501MT Waterproof Toggle Switch ((ON)-OFF-(ON))",
                 qty=5, unit_cost=3.27),
        ],
    },
    {
        "marker": "[ALIBABA-IMPORT] Illuminated LED toggle switch cover",
        "supplier_name": UNCONFIRMED_SUPPLIER,
        "supplier_notes": UNCONFIRMED_SUPPLIER_NOTES,
        "source_url": "https://www.alibaba.com/product-detail/Illuminated-LED-Toggle-Switch-Cover-with_1601269459807.html",
        "received": True,
        "shipping_usd": 6.12,
        "parts": [
            dict(part_number="ALI-LEDCOVER-RED",
                 part_name="Illuminated LED Toggle Switch Cover with Lock (Missile Flick Cover) — Red",
                 qty=20, unit_cost=0.33),
        ],
    },
    {
        "marker": "[ALIBABA-IMPORT] 19mm short push button switch",
        "supplier_name": UNCONFIRMED_SUPPLIER,
        "supplier_notes": UNCONFIRMED_SUPPLIER_NOTES,
        "source_url": "https://www.alibaba.com/product-detail/19mm-Short-Push-Button-Switch-Low_1601606670476.html",
        "received": True,
        "shipping_usd": 12.90,
        "parts": [
            dict(part_number=f"ALI-PB19-{color.upper()}",
                 part_name=f"19mm Short Push Button Switch, 6V — {color}",
                 qty=4, unit_cost=3.57)
            for color in ["Red", "Blue", "White", "Yellow", "Green", "Orange"]
        ],
    },
    {
        "marker": "[ALIBABA-IMPORT] Yonglisheng Pro Micro ATmega32U4",
        "supplier_name": UNCONFIRMED_SUPPLIER,
        "supplier_notes": UNCONFIRMED_SUPPLIER_NOTES,
        "source_url": "https://www.alibaba.com/product-detail/Yonglisheng-100-Stock-Pro-Micro-ATmega32U4_1601537101019.html",
        "received": True,  # in hand now
        "shipping_usd": None,  # still not provided — no landed-cost boost applied for this one
        "lead_time_days": 35,
        "parts": [
            dict(part_number="ALI-PROMICRO-32U4", part_name="Yonglisheng Pro Micro ATmega32U4-MU Type C, 5V/16MHz",
                 qty=20, unit_cost=3.44),
        ],
    },
    {
        "marker": "[ALIBABA-IMPORT] Kit in Roll 1007 electric wire",
        "supplier_name": "Guangzhou Renshi Electronics Co., Ltd.",
        "supplier_notes": "Confirmed seller — seen on the Alibaba order-detail page for this shipment.",
        "source_url": "https://www.alibaba.com/product-detail/Kit-in-Roll-1007-Electric-Wire_1601524908027.html",
        "received": True,  # in hand now
        "shipping_usd": 11.34,
        "lead_time_days": 35,
        "parts": [
            dict(part_number="ALI-WIRE-BLUE", part_name="Kit in Roll 1007 Electric Wire 22AWG 10m — Blue",
                 qty=1, unit_cost=1.10),
            dict(part_number="ALI-WIRE-BLACK", part_name="Kit in Roll 1007 Electric Wire 22AWG 10m — Black",
                 qty=3, unit_cost=1.10),
            dict(part_number="ALI-WIRE-WHITE", part_name="Kit in Roll 1007 Electric Wire 22AWG 10m — White",
                 qty=1, unit_cost=1.10),
            dict(part_number="ALI-WIRE-RED", part_name="Kit in Roll 1007 Electric Wire 22AWG 10m — Red",
                 qty=3, unit_cost=1.10),
            dict(part_number="ALI-WIRE-YELLOW", part_name="Kit in Roll 1007 Electric Wire 22AWG 10m — Yellow",
                 qty=1, unit_cost=1.10),
            dict(part_number="ALI-WIRE-GREEN", part_name="Kit in Roll 1007 Electric Wire 22AWG 10m — Green",
                 qty=1, unit_cost=1.10),
        ],
    },
    {
        "marker": "[ALIBABA-IMPORT] 20 sizes aluminum knob",
        "supplier_name": UNCONFIRMED_SUPPLIER,
        "supplier_notes": UNCONFIRMED_SUPPLIER_NOTES,
        "source_url": "https://www.alibaba.com/product-detail/20-sizes-Aluminum-Knob-for-both_1601668415508.html",
        "received": True,
        "shipping_usd": 10.69,
        "parts": [
            dict(part_number="ALI-KNOB-9.5X11-IND", part_name="Aluminum Knob 18T shaft 9.5x11mm — has indicator",
                 qty=16, unit_cost=0.17),
            dict(part_number="ALI-KNOB-15X10-IND", part_name="Aluminum Knob 18T shaft 15x10mm — has indicator",
                 qty=12, unit_cost=0.19),
            dict(part_number="ALI-KNOB-15X10-NOIND", part_name="Aluminum Knob 18T shaft 15x10mm — no indicator",
                 qty=15, unit_cost=0.19),
            dict(part_number="ALI-KNOB-17X10-NOIND", part_name="Aluminum Knob 18T shaft 17x10mm — no indicator",
                 qty=10, unit_cost=0.21),
            dict(part_number="ALI-KNOB-17X10-IND", part_name="Aluminum Knob 18T shaft 17x10mm — has indicator",
                 qty=10, unit_cost=0.21),
            dict(part_number="ALI-KNOB-17X13-IND", part_name="Aluminum Knob 18T shaft 17x13mm — has indicator",
                 qty=10, unit_cost=0.21),
            dict(part_number="ALI-KNOB-20X10-IND", part_name="Aluminum Knob 18T shaft 20x10mm — has indicator",
                 qty=15, unit_cost=0.22),
            dict(part_number="ALI-KNOB-20X10-NOIND", part_name="Aluminum Knob 18T shaft 20x10mm — no indicator",
                 qty=15, unit_cost=0.22),
        ],
    },
    {
        "marker": "[ALIBABA-IMPORT] EC12 metal handle rotary incremental encoder",
        "supplier_name": "Dongguan Fanrui Electronics Technology Co., Ltd.",
        "supplier_notes": "Confirmed seller — seen on the Alibaba order-detail page for this shipment.",
        "source_url": "https://www.alibaba.com/product-detail/EC12-Metal-Handle-Rotary-Incremental-Encoder_1601291540906.html",
        "received": False,  # "still en route" — combined delivery Sep 22 - Oct 19
        "shipping_usd": 13.89,
        "lead_time_days": 35,
        "parts": [
            dict(part_number="ALI-EC12-ENCODER",
                 part_name="EC12 Metal Handle Rotary Incremental Encoder (ED1223-24P-24LC-M9B7-Y22.5A7-FR, plug-in welding)",
                 qty=30, unit_cost=0.32),
        ],
    },
]


def get_or_create_supplier(db, name, notes, source_url):
    row = db.execute("SELECT id FROM suppliers WHERE supplier_name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO suppliers (supplier_name, website, currency, notes, created_at) VALUES (?,?,?,?,?)",
        (name, source_url, "USD", notes, now_str()),
    )
    db.commit()
    return cur.lastrowid


def get_or_create_part(db, part_number, part_name, unit_cost, category_id, supplier_id):
    row = db.execute("SELECT id FROM parts WHERE part_number = ?", (part_number,)).fetchone()
    if row:
        return row["id"], False
    cur = db.execute(
        "INSERT INTO parts (part_name, part_number, category_id, unit_cost, preferred_supplier_id, "
        "label_link_type, created_at) VALUES (?,?,?,?,?,?,?)",
        (part_name, part_number, category_id, unit_cost, supplier_id, "Custom URL", now_str()),
    )
    db.commit()
    return cur.lastrowid, True


def receive_and_land(db, po_id, shipment):
    lines = db.execute(
        "SELECT id, quantity_ordered FROM purchase_order_lines WHERE purchase_order_id = ?", (po_id,)
    ).fetchall()
    for line in lines:
        receive_po_line(db, line["id"], line["quantity_ordered"])
    if shipment["shipping_usd"]:
        applied = apply_landed_cost(db, po_id)
        print(f"    landed cost applied: {applied}")


def import_shipment(db, shipment, category_id):
    existing_po = db.execute(
        "SELECT id, status FROM purchase_orders WHERE notes LIKE ?", (shipment["marker"] + "%",)
    ).fetchone()
    if existing_po:
        # Already created on a prior run. If it's now flagged received=True
        # but wasn't yet (e.g. this shipment physically arrived since the
        # last run), receive it now instead of silently skipping forever —
        # this is what makes it safe to just flip a shipment's `received`
        # flag and re-run, whether or not the earlier run already happened.
        if shipment["received"] and existing_po["status"] not in ("Received", "Partially Received"):
            receive_and_land(db, existing_po["id"], shipment)
            print(f"  RECEIVED (was pending): {shipment['marker']}")
        else:
            print(f"  SKIP (already imported): {shipment['marker']}")
        return

    supplier_id = get_or_create_supplier(
        db, shipment["supplier_name"], shipment["supplier_notes"], shipment["source_url"]
    )

    part_ids = []
    for p in shipment["parts"]:
        part_id, created = get_or_create_part(
            db, p["part_number"], p["part_name"], p["unit_cost"], category_id, supplier_id
        )
        link_exists = db.execute(
            "SELECT 1 FROM part_suppliers WHERE part_id = ? AND supplier_id = ?", (part_id, supplier_id)
        ).fetchone()
        if not link_exists:
            db.execute(
                "INSERT INTO part_suppliers (part_id, supplier_id, supplier_cost, lead_time_days, source_url, preferred) "
                "VALUES (?,?,?,?,?,1)",
                (part_id, supplier_id, p["unit_cost"], shipment.get("lead_time_days"), shipment["source_url"]),
            )
        part_ids.append((part_id, p["qty"], p["unit_cost"]))
        print(f"    {'created' if created else 'exists '} part {p['part_number']}: {p['part_name']}")
    db.commit()

    expected_delivery = None
    status = "Sent"
    cur = db.execute(
        "INSERT INTO purchase_orders (po_number, supplier_id, status, expected_delivery_date, "
        "actual_freight_paid, notes) VALUES (?,?,?,?,?,?)",
        (
            generate_number("Purchase Order"), supplier_id, status, expected_delivery,
            shipment["shipping_usd"], f"{shipment['marker']} — {shipment['source_url']}",
        ),
    )
    db.commit()
    po_id = cur.lastrowid

    for part_id, qty, unit_cost in part_ids:
        db.execute(
            "INSERT INTO purchase_order_lines (purchase_order_id, part_id, quantity_ordered, unit_cost) "
            "VALUES (?,?,?,?)",
            (po_id, part_id, qty, unit_cost),
        )
    db.commit()

    if shipment["received"]:
        receive_and_land(db, po_id, shipment)
        print(f"  IMPORTED (received): {shipment['marker']} — PO created")
    else:
        print(f"  IMPORTED (in transit, not yet received): {shipment['marker']} — PO created")


def main():
    app = create_app()
    with app.app_context():
        db = get_db()
        electronics_id = db.execute("SELECT id FROM part_categories WHERE name = 'Electronics'").fetchone()
        hardware_id = db.execute("SELECT id FROM part_categories WHERE name = 'Hardware'").fetchone()
        electronics_id = electronics_id["id"] if electronics_id else None
        hardware_id = hardware_id["id"] if hardware_id else None

        for shipment in SHIPMENTS:
            is_hardware = "knob" in shipment["marker"].lower()
            category_id = hardware_id if is_hardware else electronics_id
            print(f"Importing: {shipment['marker']}")
            import_shipment(db, shipment, category_id)

        print("\nDone. Still pending (no data given yet): RP2040 Pico, DuPont jumper "
              "cables, MT3608 booster board, 1N4148 diodes — $11.22 shipping noted, "
              "no per-item price/qty yet.")


if __name__ == "__main__":
    main()
