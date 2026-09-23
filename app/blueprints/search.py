from flask import Blueprint, render_template, request
from ..db import get_db

bp = Blueprint("search", __name__, url_prefix="/search")


@bp.route("/")
def index():
    q = request.args.get("q", "").strip()
    results = {}
    if q:
        db = get_db()
        like = f"%{q}%"
        results["parts"] = db.execute(
            "SELECT id, part_name, part_number FROM parts WHERE part_name LIKE ? OR part_number LIKE ? LIMIT 10",
            (like, like),
        ).fetchall()
        results["kits"] = db.execute(
            "SELECT id, kit_name, sku FROM kits WHERE kit_name LIKE ? OR sku LIKE ? LIMIT 10", (like, like)
        ).fetchall()
        results["clients"] = db.execute(
            "SELECT id, client_name, email FROM clients WHERE client_name LIKE ? OR email LIKE ? LIMIT 10",
            (like, like),
        ).fetchall()
        results["suppliers"] = db.execute(
            "SELECT id, supplier_name, supplier_code FROM suppliers WHERE supplier_name LIKE ? OR supplier_code LIKE ? LIMIT 10",
            (like, like),
        ).fetchall()
        results["sales_orders"] = db.execute(
            "SELECT id, order_number FROM sales_orders WHERE order_number LIKE ? LIMIT 10", (like,)
        ).fetchall()
        results["quotes"] = db.execute(
            "SELECT id, quote_number FROM quotes WHERE quote_number LIKE ? LIMIT 10", (like,)
        ).fetchall()
        results["invoices"] = db.execute(
            "SELECT id, invoice_number FROM invoices WHERE invoice_number LIKE ? LIMIT 10", (like,)
        ).fetchall()
        results["builds"] = db.execute(
            "SELECT id, build_number, serial_number FROM builds WHERE build_number LIKE ? OR serial_number LIKE ? LIMIT 10",
            (like, like),
        ).fetchall()
        results["purchase_orders"] = db.execute(
            "SELECT id, po_number FROM purchase_orders WHERE po_number LIKE ? LIMIT 10", (like,)
        ).fetchall()
        results["rmas"] = db.execute(
            "SELECT id, rma_number FROM rmas WHERE rma_number LIKE ? LIMIT 10", (like,)
        ).fetchall()
        results["batches"] = db.execute(
            "SELECT id, batch_number FROM batch_runs WHERE batch_number LIKE ? LIMIT 10", (like,)
        ).fetchall()
        results["assets"] = db.execute(
            "SELECT id, asset_name FROM assets WHERE asset_name LIKE ? LIMIT 10", (like,)
        ).fetchall()
    total = sum(len(v) for v in results.values())
    return render_template("search/index.html", q=q, results=results, total=total)
