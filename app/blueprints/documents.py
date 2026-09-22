from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db
from ..utils import save_upload

bp = Blueprint("documents", __name__, url_prefix="/documents")


def _lookups(db):
    return {
        "document_types": db.execute("SELECT * FROM document_types WHERE active=1 ORDER BY name").fetchall(),
        "clients": db.execute("SELECT id, client_name FROM clients ORDER BY client_name").fetchall(),
        "suppliers": db.execute("SELECT id, supplier_name FROM suppliers ORDER BY supplier_name").fetchall(),
        "purchase_orders": db.execute("SELECT id, po_number FROM purchase_orders ORDER BY po_number DESC").fetchall(),
        "sales_orders": db.execute("SELECT id, order_number FROM sales_orders ORDER BY order_number DESC").fetchall(),
        "kits": db.execute("SELECT id, kit_name FROM kits ORDER BY kit_name").fetchall(),
        "builds": db.execute("SELECT id, build_number FROM builds ORDER BY build_number DESC").fetchall(),
    }


@bp.route("/")
def index():
    db = get_db()
    type_id = request.args.get("type_id", "")
    sql = (
        "SELECT d.*, dt.name AS type_name, "
        "c.client_name, s.supplier_name, po.po_number, so.order_number, k.kit_name, b.build_number "
        "FROM documents d "
        "LEFT JOIN document_types dt ON dt.id = d.document_type_id "
        "LEFT JOIN clients c ON c.id = d.related_client_id "
        "LEFT JOIN suppliers s ON s.id = d.related_supplier_id "
        "LEFT JOIN purchase_orders po ON po.id = d.related_purchase_order_id "
        "LEFT JOIN sales_orders so ON so.id = d.related_sales_order_id "
        "LEFT JOIN kits k ON k.id = d.related_kit_id "
        "LEFT JOIN builds b ON b.id = d.related_build_id WHERE 1=1"
    )
    args = []
    if type_id:
        sql += " AND d.document_type_id = ?"
        args.append(type_id)
    sql += " ORDER BY d.upload_date DESC"
    documents = db.execute(sql, args).fetchall()
    return render_template("documents/index.html", documents=documents, type_id=type_id, **_lookups(db))


@bp.route("/upload", methods=["POST"])
def upload():
    db = get_db()
    f = request.form
    path = save_upload(request.files.get("file"), "documents")
    if not path:
        flash("Please choose a file to upload.", "error")
        return redirect(url_for("documents.index"))
    db.execute(
        "INSERT INTO documents (document_name, document_type_id, file_path, related_client_id, related_supplier_id, "
        "related_purchase_order_id, related_sales_order_id, related_kit_id, related_build_id, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (f.get("document_name") or request.files["file"].filename, f.get("document_type_id") or None, path,
         f.get("related_client_id") or None, f.get("related_supplier_id") or None,
         f.get("related_purchase_order_id") or None, f.get("related_sales_order_id") or None,
         f.get("related_kit_id") or None, f.get("related_build_id") or None, f.get("notes")),
    )
    db.commit()
    flash("Document uploaded.", "success")
    return redirect(url_for("documents.index"))


@bp.route("/<int:doc_id>/delete", methods=["POST"])
def delete(doc_id):
    db = get_db()
    db.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    db.commit()
    flash("Document removed.", "success")
    return redirect(url_for("documents.index"))
