from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db

bp = Blueprint("clients", __name__, url_prefix="/clients")


@bp.route("/")
def index():
    db = get_db()
    q = request.args.get("q", "").strip()
    status = request.args.get("status", "")
    sql = "SELECT * FROM clients WHERE 1=1"
    args = []
    if q:
        sql += " AND (client_name LIKE ? OR company LIKE ? OR email LIKE ?)"
        args += [f"%{q}%"] * 3
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY client_name"
    clients = db.execute(sql, args).fetchall()
    return render_template("clients/index.html", clients=clients, q=q, status=status)


@bp.route("/new", methods=["GET", "POST"])
def new():
    db = get_db()
    payment_terms = db.execute("SELECT * FROM client_payment_terms WHERE active=1 ORDER BY name").fetchall()
    if request.method == "POST":
        f = request.form
        default_pt = f.get("payment_term_id") or db.execute(
            "SELECT default_client_payment_term_id FROM company_settings WHERE id=1"
        ).fetchone()["default_client_payment_term_id"]
        cur = db.execute(
            "INSERT INTO clients (client_name, company, email, phone, client_type, payment_term_id, "
            "client_since, status, notes) VALUES (?,?,?,?,?,?,?,?,?)",
            (f["client_name"], f.get("company"), f.get("email"), f.get("phone"),
             f.get("client_type", "Individual"), default_pt or None, f.get("client_since") or None,
             f.get("status", "Active"), f.get("notes")),
        )
        db.commit()
        flash("Client created.", "success")
        return redirect(url_for("clients.detail", client_id=cur.lastrowid))
    return render_template("clients/form.html", client=None, payment_terms=payment_terms)


@bp.route("/<int:client_id>")
def detail(client_id):
    db = get_db()
    client = db.execute("SELECT * FROM clients WHERE id=?", (client_id,)).fetchone()
    if client is None:
        flash("Client not found.", "error")
        return redirect(url_for("clients.index"))
    addresses = db.execute("SELECT ca.*, co.country_name FROM client_addresses ca "
                            "JOIN countries co ON co.id=ca.country_id WHERE client_id=?", (client_id,)).fetchall()
    contacts = db.execute("SELECT * FROM client_contacts WHERE client_id=? ORDER BY is_primary_contact DESC, contact_name", (client_id,)).fetchall()
    sales_orders = db.execute("SELECT * FROM sales_orders WHERE client_id=? ORDER BY order_date DESC", (client_id,)).fetchall()
    quotes = db.execute("SELECT * FROM quotes WHERE client_id=? ORDER BY quote_date DESC", (client_id,)).fetchall()
    invoices = db.execute("SELECT * FROM invoices WHERE client_id=? ORDER BY invoice_date DESC", (client_id,)).fetchall()
    countries = db.execute("SELECT * FROM countries WHERE active=1 ORDER BY country_name").fetchall()
    payment_terms = db.execute("SELECT * FROM client_payment_terms WHERE active=1 ORDER BY name").fetchall()
    return render_template(
        "clients/detail.html", client=client, addresses=addresses, contacts=contacts,
        sales_orders=sales_orders, quotes=quotes, invoices=invoices, countries=countries,
        payment_terms=payment_terms,
    )


@bp.route("/<int:client_id>/edit", methods=["POST"])
def edit(client_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE clients SET client_name=?, company=?, email=?, phone=?, client_type=?, "
        "payment_term_id=?, client_since=?, status=?, notes=? WHERE id=?",
        (f["client_name"], f.get("company"), f.get("email"), f.get("phone"), f.get("client_type"),
         f.get("payment_term_id") or None, f.get("client_since") or None, f.get("status"), f.get("notes"), client_id),
    )
    db.commit()
    flash("Client updated.", "success")
    return redirect(url_for("clients.detail", client_id=client_id))


@bp.route("/<int:client_id>/addresses/new", methods=["POST"])
def add_address(client_id):
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO client_addresses (client_id, address_label, address_line1, address_line2, city, "
        "state_region, postcode, country_id, is_default_shipping, is_default_billing, notes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (client_id, f.get("address_label"), f.get("address_line1"), f.get("address_line2"), f.get("city"),
         f.get("state_region"), f.get("postcode"), f["country_id"],
         1 if f.get("is_default_shipping") else 0, 1 if f.get("is_default_billing") else 0, f.get("notes")),
    )
    db.commit()
    flash("Address added.", "success")
    return redirect(url_for("clients.detail", client_id=client_id))


@bp.route("/<int:client_id>/addresses/<int:address_id>/delete", methods=["POST"])
def delete_address(client_id, address_id):
    db = get_db()
    db.execute("DELETE FROM client_addresses WHERE id=? AND client_id=?", (address_id, client_id))
    db.commit()
    return redirect(url_for("clients.detail", client_id=client_id))


@bp.route("/<int:client_id>/contacts/new", methods=["POST"])
def add_contact(client_id):
    db = get_db()
    f = request.form
    if f.get("is_primary_contact"):
        db.execute("UPDATE client_contacts SET is_primary_contact=0 WHERE client_id=?", (client_id,))
    db.execute(
        "INSERT INTO client_contacts (contact_name, client_id, role_title, email, phone, is_primary_contact, notes) "
        "VALUES (?,?,?,?,?,?,?)",
        (f["contact_name"], client_id, f.get("role_title"), f.get("email"), f.get("phone"),
         1 if f.get("is_primary_contact") else 0, f.get("notes")),
    )
    db.commit()
    flash("Contact added.", "success")
    return redirect(url_for("clients.detail", client_id=client_id))


@bp.route("/<int:client_id>/contacts/<int:contact_id>/delete", methods=["POST"])
def delete_contact(client_id, contact_id):
    db = get_db()
    db.execute("DELETE FROM client_contacts WHERE id=? AND client_id=?", (contact_id, client_id))
    db.commit()
    return redirect(url_for("clients.detail", client_id=client_id))
