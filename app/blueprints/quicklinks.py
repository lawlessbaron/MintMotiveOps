import io
from flask import Blueprint, render_template, request, redirect, url_for, flash, send_file, abort
from ..db import get_db

bp = Blueprint("quicklinks", __name__, url_prefix="/quicklinks")

try:
    import qrcode
    QR_AVAILABLE = True
except ImportError:
    # qrcode[pil] needs internet access to install (see requirements.txt) —
    # not available in every environment this app might run in. The page
    # falls back to showing plain copyable URLs instead of QR images when
    # this import fails, rather than crashing the whole module.
    QR_AVAILABLE = False


@bp.route("/")
def index():
    db = get_db()
    links = db.execute(
        """SELECT ql.*, p.part_name, k.kit_name, c.client_name FROM quick_links ql
           LEFT JOIN parts p ON p.id = ql.related_part_id
           LEFT JOIN kits k ON k.id = ql.related_kit_id
           LEFT JOIN clients c ON c.id = ql.related_client_id
           ORDER BY ql.link_name"""
    ).fetchall()
    templates = db.execute("SELECT * FROM sticker_templates ORDER BY template_name").fetchall()
    parts = db.execute("SELECT id, part_name, label_link_type, label_url FROM parts ORDER BY part_name").fetchall()
    kits = db.execute("SELECT id, kit_name, customer_label_link_type, customer_label_url FROM kits ORDER BY kit_name").fetchall()
    clients = db.execute("SELECT id, client_name FROM clients ORDER BY client_name").fetchall()
    return render_template(
        "quicklinks/index.html", links=links, templates=templates,
        parts=parts, kits=kits, clients=clients, qr_available=QR_AVAILABLE,
    )


@bp.route("/add", methods=["POST"])
def add():
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO quick_links (link_name, link_type, url, related_part_id, related_kit_id, related_client_id, active, notes) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (f["link_name"], f.get("link_type"), f["url"], f.get("related_part_id") or None,
         f.get("related_kit_id") or None, f.get("related_client_id") or None,
         1 if f.get("active") else 0, f.get("notes")),
    )
    db.commit()
    flash("Quick Link added.", "success")
    return redirect(url_for("quicklinks.index"))


@bp.route("/<int:link_id>/edit", methods=["POST"])
def edit(link_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE quick_links SET link_name=?, link_type=?, url=?, related_part_id=?, related_kit_id=?, "
        "related_client_id=?, active=?, notes=? WHERE id=?",
        (f["link_name"], f.get("link_type"), f["url"], f.get("related_part_id") or None,
         f.get("related_kit_id") or None, f.get("related_client_id") or None,
         1 if f.get("active") else 0, f.get("notes"), link_id),
    )
    db.commit()
    flash("Quick Link updated.", "success")
    return redirect(url_for("quicklinks.index"))


@bp.route("/sticker-templates/add", methods=["POST"])
def add_template():
    db = get_db()
    f = request.form
    db.execute(
        "INSERT INTO sticker_templates (template_name, material, width_mm, height_mm, notes) VALUES (?,?,?,?,?)",
        (f["template_name"], f.get("material"), f.get("width_mm") or None, f.get("height_mm") or None, f.get("notes")),
    )
    db.commit()
    flash("Sticker template added.", "success")
    return redirect(url_for("quicklinks.index"))


@bp.route("/sticker-templates/<int:tpl_id>/edit", methods=["POST"])
def edit_template(tpl_id):
    db = get_db()
    f = request.form
    db.execute(
        "UPDATE sticker_templates SET template_name=?, material=?, width_mm=?, height_mm=?, notes=? WHERE id=?",
        (f["template_name"], f.get("material"), f.get("width_mm") or None, f.get("height_mm") or None,
         f.get("notes"), tpl_id),
    )
    db.commit()
    flash("Sticker template updated.", "success")
    return redirect(url_for("quicklinks.index"))


# ---------------------------------------------------------------------------
# QR code image generation — one small PNG per part/kit label URL, drawn on
# the fly from whatever URL that record currently resolves to. Nothing is
# stored on disk; each request just redraws the code, so it's always in
# sync with the record's current Label Link Type / Label URL.
# ---------------------------------------------------------------------------

def _qr_png_response(data):
    if not QR_AVAILABLE:
        abort(404)
    img = qrcode.make(data, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", max_age=0)


@bp.route("/qr/part/<int:part_id>.png")
def qr_part(part_id):
    db = get_db()
    part = db.execute(
        "SELECT id, label_link_type, label_url FROM parts WHERE id=?", (part_id,)
    ).fetchone()
    if part is None:
        abort(404)
    target = part["label_url"] or (
        url_for("parts.detail", part_id=part["id"], _external=True)
        if part["label_link_type"] == "Internal Record" else None
    )
    if not target:
        abort(404)
    return _qr_png_response(target)


@bp.route("/qr/kit/<int:kit_id>.png")
def qr_kit(kit_id):
    db = get_db()
    kit = db.execute(
        "SELECT id, customer_label_url FROM kits WHERE id=?", (kit_id,)
    ).fetchone()
    if kit is None or not kit["customer_label_url"]:
        abort(404)
    return _qr_png_response(kit["customer_label_url"])


@bp.route("/qr/build/<int:build_id>.png")
def qr_build(build_id):
    """Scanning this from a shipped unit's label opens Start RMA with the
    build pre-selected — see rmas.new's build_id query param."""
    db = get_db()
    build = db.execute("SELECT id FROM builds WHERE id=?", (build_id,)).fetchone()
    if build is None:
        abort(404)
    target = url_for("rmas.new", build_id=build["id"], _external=True)
    return _qr_png_response(target)


@bp.route("/qr/link/<int:link_id>.png")
def qr_link(link_id):
    db = get_db()
    link = db.execute("SELECT id, url FROM quick_links WHERE id=?", (link_id,)).fetchone()
    if link is None or not link["url"]:
        abort(404)
    return _qr_png_response(link["url"])
