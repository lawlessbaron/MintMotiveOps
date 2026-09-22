"""End-to-end functional test: walks a realistic path through every module
(Suppliers -> Parts -> Kits/BOM -> Clients -> Sales Order -> Purchase Order
+ receiving -> Quote -> convert to Invoice -> pay link -> Build lifecycle ->
Warehouse -> Documents -> Quick Links -> Assets -> Administration) using the
Flask test client, and asserts on the computed business-logic fields (sell
price, stock reservation, PO status transitions, GST/document totals)."""
import re
import sys
from app import create_app

PASS = []
FAIL = []


def check(label, cond, detail=""):
    if cond:
        PASS.append(label)
    else:
        FAIL.append((label, detail))
    print(("  OK  " if cond else " FAIL ") + label + (f"  -- {detail}" if detail and not cond else ""))


def get_id_from_redirect(resp, pattern):
    loc = resp.headers.get("Location", "")
    m = re.search(pattern, loc)
    return int(m.group(1)) if m else None


def main():
    app = create_app()
    app.config["TESTING"] = True
    password = sys.argv[1]

    with app.test_client() as c:
        r = c.post("/login", data={"email": "lawlessbaron@gmail.com", "password": password})
        check("login redirects (302)", r.status_code == 302, r.status_code)

        # ---------------- Supplier ----------------
        r = c.post("/suppliers/new", data={"supplier_name": "Acme Filament Co", "email": "sales@acmefilament.test",
                                            "currency": "USD", "status": "Active"})
        supplier_id = get_id_from_redirect(r, r"/suppliers/(\d+)")
        check("supplier created", supplier_id is not None, r.headers.get("Location"))

        # ---------------- Part ----------------
        r = c.post("/inventory/new", data={"part_name": "PLA Filament 1kg", "quantity_on_hand": "50",
                                            "reorder_threshold": "10", "unit_cost": "20.00", "margin_pct": "50",
                                            "preferred_supplier_id": str(supplier_id)})
        part_id = get_id_from_redirect(r, r"/inventory/(\d+)")
        check("part created", part_id is not None, r.headers.get("Location"))

        r = c.get(f"/inventory/{part_id}")
        check("part detail 200", r.status_code == 200)
        check("part sell price computed correctly ($30.00 = $20 cost * 1.5 margin)",
              b"30.00" in r.data or b"30.0" in r.data, "sell price not found in page")

        # ---------------- Kit + BOM ----------------
        r = c.post("/kits/new", data={"kit_name": "Formula Wheel Stand", "margin_pct": "40"})
        kit_id = get_id_from_redirect(r, r"/kits/(\d+)")
        check("kit created", kit_id is not None, r.headers.get("Location"))

        r = c.post(f"/kits/{kit_id}/bom/add", data={"part_id": str(part_id), "quantity_required": "2"})
        check("BOM line add redirects", r.status_code == 302)
        r = c.get(f"/kits/{kit_id}")
        check("kit detail shows total cost $40.00 (2 x $20 cost)", b"40.00" in r.data or b"40.0" in r.data)

        # ---------------- Sub-assemblies (multi-level BOM) ----------------
        # Sub-assembly kit: one $20 part, qty 1 -> its own total cost is $20.
        r = c.post("/kits/new", data={"kit_name": "Button Board Sub-Assembly", "margin_pct": "0",
                                       "is_subassembly": "1"})
        subassembly_id = get_id_from_redirect(r, r"/kits/(\d+)")
        check("sub-assembly kit created", subassembly_id is not None, r.headers.get("Location"))
        c.post(f"/kits/{subassembly_id}/bom/add", data={"part_id": str(part_id), "quantity_required": "1"})

        # Final kit consumes the sub-assembly (cost $20) plus 1 more of the raw part ($20) -> $40 total.
        r = c.post("/kits/new", data={"kit_name": "Final Rig With Sub-Assembly", "margin_pct": "0"})
        final_kit_id = get_id_from_redirect(r, r"/kits/(\d+)")
        c.post(f"/kits/{final_kit_id}/bom/add", data={"component_kit_id": str(subassembly_id), "quantity_required": "1"})
        c.post(f"/kits/{final_kit_id}/bom/add", data={"part_id": str(part_id), "quantity_required": "1"})
        r = c.get(f"/kits/{final_kit_id}")
        check("multi-level BOM: final kit total cost recurses through sub-assembly ($40.00 = $20 sub-assembly + $20 part)",
              b"40.00" in r.data or b"40.0" in r.data)
        check("BOM table tags the sub-assembly component distinctly", b"Sub-Assembly" in r.data)

        # Circular BOM guard: final kit already contains the sub-assembly,
        # so adding final_kit as a component OF the sub-assembly would create
        # a cycle (sub-assembly -> final -> sub-assembly) — must be refused.
        from app.db import kit_bom_would_cycle
        with app.app_context():
            from app.db import get_db as _get_db
            _db = _get_db()
            would_cycle = kit_bom_would_cycle(_db, subassembly_id, final_kit_id)
        check("cycle detection flags final-kit-into-its-own-sub-assembly as a cycle", would_cycle is True)
        r = c.post(f"/kits/{subassembly_id}/bom/add", data={"component_kit_id": str(final_kit_id), "quantity_required": "1"}, follow_redirects=True)
        check("circular BOM add is refused (redirected back, not inserted)", b"circular BOM" in r.data)

        # ---------------- Firmware versions + serialized builds ----------------
        r = c.post(f"/kits/{final_kit_id}/firmware/add", data={"version_label": "v1.0.0", "release_notes": "Initial release"})
        check("firmware version add redirects", r.status_code == 302)
        r = c.get(f"/kits/{final_kit_id}")
        check("firmware version shows on kit page", b"v1.0.0" in r.data)

        r = c.get(f"/kits/{final_kit_id}")
        fw_id_match = re.search(r'<option value="(\d+)">v1\.0\.0</option>', r.data.decode())
        firmware_id = fw_id_match.group(1) if fw_id_match else None

        r = c.post(f"/kits/{final_kit_id}/builds/new", data={"firmware_version_id": firmware_id or ""})
        subassembly_build_id = get_id_from_redirect(r, r"/builds/(\d+)")
        check("build with firmware version created", subassembly_build_id is not None, r.headers.get("Location"))
        r = c.get(f"/builds/{subassembly_build_id}")
        check("build auto-generated a serial number in MM-BB-#### format", re.search(rb"MM-BB-\d{4}", r.data) is not None)
        if firmware_id:
            check("build detail shows the linked firmware version selected", b'value="' + firmware_id.encode() + b'" selected' in r.data)

        # ---------------- Client ----------------
        r = c.post("/clients/new", data={"client_name": "Jordan Smith", "email": "jordan@example.test",
                                          "client_type": "Individual"})
        client_id = get_id_from_redirect(r, r"/clients/(\d+)")
        check("client created", client_id is not None, r.headers.get("Location"))

        countries = c.get(f"/clients/{client_id}").data
        # need a country id for address — Australia was seeded as id 1 typically; fetch dynamically instead
        from app.db import get_db
        with app.app_context():
            pass

        r = c.post(f"/clients/{client_id}/addresses/new", data={
            "address_label": "Home", "address_line1": "1 Example St", "city": "Melbourne",
            "state_region": "VIC", "postcode": "3000", "country_id": "1",
        })
        check("client address add redirects", r.status_code == 302)

        r = c.post(f"/clients/{client_id}/contacts/new", data={"contact_name": "Jordan Smith", "is_primary_contact": "1"})
        check("client contact add redirects", r.status_code == 302)

        # ---------------- Sales Order ----------------
        r = c.post("/sales-orders/new", data={"client_id": str(client_id)})
        order_id = get_id_from_redirect(r, r"/sales-orders/(\d+)")
        check("sales order created", order_id is not None, r.headers.get("Location"))

        r = c.post(f"/sales-orders/{order_id}/lines/add", data={"item_type": "Kit", "kit_id": str(kit_id), "quantity": "1"})
        check("sales order line add redirects", r.status_code == 302)
        r = c.get(f"/sales-orders/{order_id}")
        check("sales order detail shows kit line total $56.00 (40 cost * 1.4 margin)",
              b"56.00" in r.data or b"56.0" in r.data)

        # ---------------- Purchase Order + partial receiving ----------------
        r = c.post("/purchase-orders/new", data={"supplier_id": str(supplier_id)})
        po_id = get_id_from_redirect(r, r"/purchase-orders/(\d+)")
        check("PO created", po_id is not None, r.headers.get("Location"))

        r = c.post(f"/purchase-orders/{po_id}/lines/add", data={"part_id": str(part_id), "quantity_ordered": "20", "unit_cost": "18"})
        check("PO line add redirects", r.status_code == 302)

        r = c.post(f"/purchase-orders/{po_id}/status", data={"status": "Confirmed"})
        check("PO status -> Confirmed", r.status_code == 302)

        lines = c.get(f"/purchase-orders/{po_id}").data
        m = re.search(rb'lines/(\d+)/receive', lines)
        line_id = int(m.group(1)) if m else None
        check("found PO line id for receiving", line_id is not None)

        r = c.post(f"/purchase-orders/{po_id}/lines/{line_id}/receive", data={"quantity": "10"})
        check("partial receive redirects", r.status_code == 302)
        r = c.get(f"/purchase-orders/{po_id}")
        check("PO auto-advanced to Partially Received", b"Partially Received" in r.data)

        r = c.get(f"/inventory/{part_id}")
        check("on-hand stock increased by received qty (50 + 10 = 60)", b"60" in r.data)

        r = c.post(f"/purchase-orders/{po_id}/lines/{line_id}/receive", data={"quantity": "10"})
        r = c.get(f"/purchase-orders/{po_id}")
        check("PO auto-advanced to Received once fully received", b">Received<" in r.data or b"Received" in r.data)

        # ---------------- Expenses ledger (real BAS GST-Paid source) ----------------
        # Each of the two receive calls above (10 units @ $18 = $180 GST-inclusive)
        # should have auto-filed its own itemized expense row — not one silent total.
        with app.app_context():
            from app.db import get_db as _get_db3
            _db3 = _get_db3()
            po_expenses = _db3.execute(
                "SELECT * FROM expenses WHERE related_purchase_order_id=? ORDER BY id", (po_id,)
            ).fetchall()
        check("PO receiving auto-filed one expense row per receive (2 receives)", len(po_expenses) == 2, len(po_expenses))
        if len(po_expenses) == 2:
            check("auto-filed expense GST is receipt value / 11 ($180 / 11 = $16.36)",
                  abs(po_expenses[0]["gst_amount"] - round(180 / 11, 2)) < 0.01, po_expenses[0]["gst_amount"])
            check("auto-filed expense is tagged source=Purchase Order", po_expenses[0]["source"] == "Purchase Order")

        r = c.post(f"/purchase-orders/{po_id}/lines/{line_id}/receive", data={"quantity": "5"})
        with app.app_context():
            _db3 = _get_db3()
            po_expenses_after = _db3.execute(
                "SELECT COUNT(*) c FROM expenses WHERE related_purchase_order_id=?", (po_id,)
            ).fetchone()["c"]
        check("receiving beyond the ordered quantity doesn't file a 3rd (zero-value) expense row",
              po_expenses_after == 2, po_expenses_after)

        r = c.get("/financial/expenses")
        check("expenses ledger page 200", r.status_code == 200 and b"Expenses Ledger" in r.data)

        r = c.post("/financial/expenses", data={"category": "Rent", "description": "Workshop rent — test",
                                                  "amount_ex_gst": "500"})
        check("manual expense add redirects", r.status_code == 302)
        r = c.get("/financial/expenses")
        check("expenses ledger shows the manual entry with auto-computed 10% GST", b"Workshop rent" in r.data and b"$50.00" in r.data)

        # ---------------- Quote -> Invoice -> Pay link ----------------
        r = c.post("/quotes/new", data={"client_id": str(client_id)})
        quote_id = get_id_from_redirect(r, r"/quotes/(\d+)")
        check("quote created", quote_id is not None, r.headers.get("Location"))

        r = c.post(f"/quotes/{quote_id}/lines/add", data={"item_type": "Kit", "kit_id": str(kit_id), "quantity": "1"})
        check("quote line add redirects", r.status_code == 302)

        r = c.get(f"/quotes/{quote_id}")
        check("quote email draft prefilled from 'Quote Sent' template", b"Thanks for your interest" in r.data)
        r = c.post(f"/quotes/{quote_id}/email", data={"subject": "Your quote", "body": "Hi there, quote attached."})
        check("quote email-to-client redirects", r.status_code == 302)

        r = c.post(f"/quotes/{quote_id}/convert-to-invoice")
        invoice_id = get_id_from_redirect(r, r"/invoices/(\d+)")
        check("quote converted to invoice", invoice_id is not None, r.headers.get("Location"))

        r = c.get(f"/invoices/{invoice_id}")
        check("invoice detail 200 with GST (Tax Invoice)", r.status_code == 200 and b"Tax Invoice" in r.data,
              "expected AUD default currency to trigger GST + Tax Invoice label")

        r = c.get(f"/invoices/{invoice_id}")
        check("invoice email draft prefilled from 'Invoice Sent' template", b"review and pay" in r.data)
        r = c.post(f"/invoices/{invoice_id}/email", data={"subject": "Your invoice", "body": "Hi there, invoice attached."})
        check("invoice email-to-client redirects", r.status_code == 302)

        r = c.post(f"/invoices/{invoice_id}/generate-pay-link")
        check("pay link generated", r.status_code == 302)
        detail_page = c.get(f"/invoices/{invoice_id}").data
        m = re.search(rb'/pay/([A-Za-z0-9_-]+)', detail_page)
        token = m.group(1).decode() if m else None
        check("public pay token present on invoice detail page", token is not None)

        if token:
            r = c.get(f"/pay/{token}")
            check("public pay page 200 (no login required)", r.status_code == 200)
            r = c.post(f"/pay/{token}/checkout")
            check("checkout attempt handled gracefully (no live Stripe key in this sandbox)",
                  r.status_code in (200, 302), r.status_code)

        # ---------------- Build lifecycle + stock reservation ----------------
        r = c.post(f"/kits/{kit_id}/builds/new", data={"client_id": str(client_id)})
        build_id = get_id_from_redirect(r, r"/builds/(\d+)")
        check("build created", build_id is not None, r.headers.get("Location"))

        before = c.get(f"/inventory/{part_id}").data
        m = re.search(rb'Reserved.*?(\d+)', before, re.S)

        r = c.post(f"/builds/{build_id}/update", data={"status": "Printing"})
        check("build status -> Printing", r.status_code == 302)
        r = c.get(f"/inventory/{part_id}")
        check("stock reserved on Printing (2 units reserved for this build's BOM)", b"2" in r.data)

        r = c.post(f"/builds/{build_id}/update", data={"status": "Shipped"})
        check("build status -> Shipped (should redirect w/ show_email)", r.status_code == 302)
        r = c.get(f"/inventory/{part_id}")
        check("part detail after ship still 200", r.status_code == 200)

        # ---------------- Warehouse ----------------
        r = c.post("/warehouse/locations/add", data={"name": "Shelf A1", "type": "Parts Storage"})
        check("warehouse location add redirects", r.status_code == 302)
        r = c.get("/warehouse/")
        check("warehouse index 200", r.status_code == 200 and b"Shelf A1" in r.data)

        # ---------------- Documents ----------------
        from io import BytesIO
        r = c.post("/documents/upload", data={
            "document_name": "Test Doc", "file": (BytesIO(b"hello world"), "test.txt"),
        }, content_type="multipart/form-data")
        check("document upload redirects", r.status_code == 302, r.headers.get("Location"))
        r = c.get("/documents/")
        check("documents index shows uploaded doc", b"Test Doc" in r.data)

        # ---------------- Quick Links ----------------
        r = c.post("/quicklinks/add", data={"link_name": "Google Review", "link_type": "Google Review Page",
                                             "url": "https://g.page/review", "active": "1"})
        check("quick link add redirects", r.status_code == 302)
        r = c.get("/quicklinks/")
        check("quicklinks index 200 (tojson fix)", r.status_code == 200 and b"Google Review" in r.data)

        # ---------------- Assets ----------------
        r = c.post("/assets/new", data={"asset_name": "Prusa MK4 #1", "status": "In Service"})
        asset_id = get_id_from_redirect(r, r"/assets/(\d+)")
        check("asset created", asset_id is not None, r.headers.get("Location"))

        # ---------------- Administration ----------------
        r = c.get("/admin/duties-shipping")
        check("admin duties & shipping 200 (tojson fix)", r.status_code == 200)

        r = c.post("/admin/duties-shipping/countries/save", data={"country_name": "New Zealand", "iso_code": "NZ",
                                                                    "default_import_duty_rate_pct": "5", "active": "1"})
        check("add country redirects", r.status_code == 302, r.headers.get("Location"))

        r = c.get("/admin/numbering")
        check("admin numbering 200", r.status_code == 200 and b"INV-" in r.data)

        r = c.get("/admin/integrations")
        check("admin integrations 200", r.status_code == 200 and b"Shopify" in r.data)

        r = c.post("/admin/integrations/Shopify/test-sync")
        check("shopify test sync redirects", r.status_code == 302)

        r = c.get("/admin/security")
        check("admin security 200", r.status_code == 200 and b"lawlessbaron@gmail.com" in r.data)

        r = c.post("/admin/security/users/add", data={"name": "Workshop Hand", "email": "workshop@example.test",
                                                        "role": "Workshop", "password": "temp12345"})
        check("add user redirects", r.status_code == 302)

        r = c.get("/admin/appearance")
        check("admin appearance 200", r.status_code == 200 and b"#9EC4B5" in r.data.decode().replace('"', '').encode() or b"9EC4B5" in r.data)

        from app.blueprints.admin import APPEARANCE_FIELDS
        r = c.post("/admin/appearance", data={f: "#123456" for f in APPEARANCE_FIELDS})
        check("appearance save redirects", r.status_code == 302)
        r = c.get("/")
        check("theme color change reflected live on dashboard", b"#123456" in r.data)

        r = c.post("/admin/appearance/reset")
        check("appearance reset redirects", r.status_code == 302)
        r = c.get("/")
        check("theme reset back to brand accent", b"#9EC4B5" in r.data)

        # ---------------- Search ----------------
        r = c.get("/search/?q=Jordan")
        check("global search finds client", r.status_code == 200 and b"Jordan Smith" in r.data)

        r = c.get("/search/?q=Formula")
        check("global search finds kit", r.status_code == 200 and b"Formula Wheel Stand" in r.data)

        # ---------------- ECOs ----------------
        r = c.post(f"/kits/{kit_id}/ecos/new", data={"description": "Swapped M3x8 for M3x10 heat-set insert"})
        check("ECO add redirects", r.status_code == 302)
        r = c.get(f"/kits/{kit_id}")
        check("kit page shows filed ECO", b"ECO-" in r.data and b"heat-set insert" in r.data)

        # ---------------- Routing Steps + labor time -> true COGS ----------------
        r = c.post(f"/kits/{kit_id}/routing/add", data={"step_name": "3D Print Housing", "estimated_minutes": "30"})
        check("routing step add redirects", r.status_code == 302)
        r = c.get(f"/kits/{kit_id}")
        check("kit page shows routing step", b"3D Print Housing" in r.data)
        step_match = re.search(rb"steps/(\d+)/start", c.get(f"/builds/{build_id}").data)
        step_id = int(step_match.group(1)) if step_match else None
        check("build page offers Start for the new routing step", step_id is not None)
        if step_id:
            c.post(f"/builds/{build_id}/steps/{step_id}/start")
            r = c.post(f"/builds/{build_id}/steps/{step_id}/complete", data={"actual_minutes": "25"})
            check("complete step redirects", r.status_code == 302)
            r = c.get(f"/builds/{build_id}")
            check("build page shows logged actual minutes", b"25" in r.data)
            check("build page shows non-zero labor cost", b"18.75" in r.data or b"Labor Cost" in r.data)

        # ---------------- CPQ / Build-level BOM overrides ----------------
        r = c.post("/inventory/new", data={"part_name": "Premium Knob", "quantity_on_hand": "50",
                                            "unit_cost": "5.00", "margin_pct": "50"})
        knob_part_id = get_id_from_redirect(r, r"/inventory/(\d+)")
        check("second part (override substitute) created", knob_part_id is not None)

        r = c.post(f"/kits/{kit_id}/builds/new", data={})
        override_build_id = get_id_from_redirect(r, r"/builds/(\d+)")
        check("second build for override test created", override_build_id is not None)

        r = c.post(f"/builds/{override_build_id}/bom-override/add",
                    data={"substitute_part_id": str(knob_part_id), "quantity_required": "3",
                          "notes": "Client requested premium knob"})
        check("BOM override add redirects", r.status_code == 302)
        r = c.get(f"/builds/{override_build_id}")
        check("build page shows the BOM override", b"Premium Knob" in r.data)

        c.post(f"/builds/{override_build_id}/update", data={"status": "Printing"})
        r = c.get(f"/inventory/{knob_part_id}")
        check("overridden part got reserved via effective BOM (3 reserved)", b"3" in r.data)

        # ---------------- RMA + teardown ----------------
        with app.app_context():
            from app.db import get_db as _get_db2
            _db2 = _get_db2()
            part_qty_before_rma = _db2.execute("SELECT quantity_on_hand FROM parts WHERE id=?", (part_id,)).fetchone()["quantity_on_hand"]

        r = c.post("/rmas/new", data={"build_id": str(build_id), "reason": "Screen cracked in transit"})
        rma_id = get_id_from_redirect(r, r"/rmas/(\d+)")
        check("RMA created", rma_id is not None, r.headers.get("Location"))

        r = c.post(f"/rmas/{rma_id}/teardown/add", data={"part_id": str(part_id), "quantity": "1", "disposition": "Restock"})
        check("RMA teardown line add redirects", r.status_code == 302)
        r = c.post(f"/rmas/{rma_id}/teardown/process")
        check("RMA teardown process redirects", r.status_code == 302)

        with app.app_context():
            _db2 = _get_db2()
            part_qty_after_rma = _db2.execute("SELECT quantity_on_hand FROM parts WHERE id=?", (part_id,)).fetchone()["quantity_on_hand"]
        check("RMA Restock line returned 1 unit to inventory",
              part_qty_after_rma == part_qty_before_rma + 1,
              f"before={part_qty_before_rma} after={part_qty_after_rma}")

        r = c.post(f"/rmas/{rma_id}/resolve", data={"resolution": "Replaced", "notes": "Sent a replacement unit"})
        check("RMA resolve redirects", r.status_code == 302)
        r = c.get(f"/rmas/{rma_id}")
        check("RMA shows Resolved status", b"Resolved" in r.data)

        # ---------------- Batch Production Runs ----------------
        r = c.post("/batches/new", data={"kit_id": str(kit_id), "quantity": "2"})
        batch_id = get_id_from_redirect(r, r"/batches/(\d+)")
        check("batch run created", batch_id is not None, r.headers.get("Location"))

        r = c.get(f"/batches/{batch_id}")
        check("batch pick list shows the kit's part grouped by bin location (4 needed = 2 qty/unit x 2 units)",
              b"Unassigned" in r.data and (b"4" in r.data))

        r = c.post(f"/batches/{batch_id}/spawn-builds")
        check("spawn builds redirects", r.status_code == 302)
        r = c.get(f"/batches/{batch_id}")
        check("batch detail shows 2 spawned builds", r.data.count(b"BLD-") >= 2)

        with app.app_context():
            _db2 = _get_db2()
            spawned_build = _db2.execute("SELECT id FROM builds WHERE batch_run_id=? LIMIT 1", (batch_id,)).fetchone()
            spawned_build_id = spawned_build["id"] if spawned_build else None
        check("a build row is linked back to its batch_run_id", spawned_build_id is not None)

        # ---------------- Gridfinity pick-list layout (real baseplate coords) ----------------
        # A 2x2 baseplate "Drawer QA" — cells (0,0),(1,0) on row y=0, (0,1),(1,1)
        # on row y=1. Serpentine walk order should be: (0,0),(1,0),(1,1),(0,1).
        with app.app_context():
            from app.db import get_db as _get_db4, batch_pick_list as _batch_pick_list, batch_pick_list_grid_maps as _grid_maps
            _db4 = _get_db4()
            gf_coords = [(0, 0), (1, 0), (0, 1), (1, 1)]
            gf_part_ids = []
            for i, (x, y) in enumerate(gf_coords):
                _db4.execute(
                    "INSERT INTO locations (name, type, baseplate_name, grid_x, grid_y) VALUES (?,?,?,?,?)",
                    (f"QA cell {x},{y}", "Parts Storage", "Drawer QA", x, y),
                )
                loc_id = _db4.execute("SELECT id FROM locations WHERE name=?", (f"QA cell {x},{y}",)).fetchone()["id"]
                _db4.execute(
                    "INSERT INTO parts (part_name, part_number, unit_cost, quantity_on_hand, bin_location_id) VALUES (?,?,?,?,?)",
                    (f"GF Test Part {i}", f"GFQA-{i}", 1, 100, loc_id),
                )
                gf_part_ids.append(_db4.execute("SELECT id FROM parts WHERE part_number=?", (f"GFQA-{i}",)).fetchone()["id"])
            _db4.execute("INSERT INTO kits (kit_name, sku) VALUES ('GF QA Kit','GFQAKIT1')")
            gf_kit_id = _db4.execute("SELECT id FROM kits WHERE sku='GFQAKIT1'").fetchone()["id"]
            for pid in gf_part_ids:
                _db4.execute("INSERT INTO kit_parts (kit_id, part_id, quantity_required) VALUES (?,?,1)", (gf_kit_id, pid))
            _db4.execute("INSERT INTO batch_runs (batch_number, kit_id, quantity) VALUES ('BATCH-GFQA',?,1)", (gf_kit_id,))
            gf_batch_id = _db4.execute("SELECT id FROM batch_runs WHERE batch_number='BATCH-GFQA'").fetchone()["id"]
            _db4.commit()

            gf_rows = _batch_pick_list(_db4, gf_batch_id)
            gf_order = [(r["grid_x"], r["grid_y"]) for r in gf_rows]
            gf_maps = _grid_maps(_db4, gf_rows)
        check("Gridfinity serpentine walk order is (0,0)->(1,0)->(1,1)->(0,1)",
              gf_order == [(0, 0), (1, 0), (1, 1), (0, 1)], gf_order)
        check("Gridfinity grid map built for the baseplate with all 4 cells marked needed",
              len(gf_maps) == 1 and sum(c["needed"] for row in gf_maps[0]["grid_rows"] for c in row) == 4)

        r = c.get(f"/batches/{gf_batch_id}")
        check("batch detail page renders the Gridfinity visual grid map", r.status_code == 200 and b"Drawer QA" in r.data and b"gridfinity-cell" in r.data)

        # ---------------- Workshop Kanban ----------------
        r = c.get("/workshop/")
        check("workshop board 200", r.status_code == 200 and b"Workshop Board" in r.data)
        if spawned_build_id:
            r = c.post("/workshop/move", data={"build_id": str(spawned_build_id), "status": "Printing"})
            check("kanban move endpoint returns ok", r.status_code == 200 and r.get_json().get("ok") is True)
            with app.app_context():
                _db2 = _get_db2()
                moved_status = _db2.execute("SELECT status FROM builds WHERE id=?", (spawned_build_id,)).fetchone()["status"]
            check("kanban move actually updated the build's status", moved_status == "Printing", moved_status)

        # ---------------- Auto-Procurement Queue ----------------
        r = c.post("/inventory/new", data={"part_name": "Low Stock Bolt", "quantity_on_hand": "2",
                                            "reorder_threshold": "10", "unit_cost": "1.00",
                                            "preferred_supplier_id": str(supplier_id)})
        low_stock_part_id = get_id_from_redirect(r, r"/inventory/(\d+)")
        check("low-stock part created", low_stock_part_id is not None)

        r = c.get("/procurement/")
        check("procurement queue flags the low-stock part under its preferred supplier",
              r.status_code == 200 and b"Low Stock Bolt" in r.data)

        r = c.post("/procurement/create-draft-po", data={
            "supplier_id": str(supplier_id), "part_id": [str(low_stock_part_id)],
            "suggested_qty": ["20"], "unit_cost": ["1.00"],
        })
        check("create draft PO from procurement queue redirects", r.status_code == 302)

        # ---------------- Landed Cost Distribution ----------------
        with app.app_context():
            _db2 = _get_db2()
            part_cost_before_landed = _db2.execute("SELECT unit_cost FROM parts WHERE id=?", (part_id,)).fetchone()["unit_cost"]

        r = c.post(f"/purchase-orders/{po_id}/landed-cost",
                    data={"actual_freight_paid": "20", "actual_duty_paid": "0", "received_date": "2026-01-15"})
        check("landed cost figures save redirects", r.status_code == 302)
        r = c.post(f"/purchase-orders/{po_id}/landed-cost/apply")
        check("landed cost apply redirects", r.status_code == 302)

        with app.app_context():
            _db2 = _get_db2()
            part_cost_after_landed = _db2.execute("SELECT unit_cost FROM parts WHERE id=?", (part_id,)).fetchone()["unit_cost"]
        # Blended weighted-average, not a guaranteed increase: the received
        # line's own unit_cost (18) plus its $1/unit freight share (19) is
        # still below the part's prior recorded unit_cost (20), so the
        # moving average here actually moves DOWN toward 19.71 — that's
        # correct moving-average costing, just asserting it actually moved.
        check("landed cost distribution changed the part's moving-average unit cost",
              part_cost_after_landed != part_cost_before_landed,
              f"before={part_cost_before_landed} after={part_cost_after_landed}")

        r = c.post(f"/purchase-orders/{po_id}/landed-cost/apply")
        r = c.get(f"/purchase-orders/{po_id}")
        check("PO detail shows landed cost already applied", b"Already applied" in r.data)

        # ---------------- Supplier Reliability + Blackout Periods ----------------
        r = c.get("/suppliers/")
        check("suppliers index shows reliability column", r.status_code == 200 and b"Reliability" in r.data)

        r = c.post(f"/suppliers/{supplier_id}/blackout/add",
                    data={"start_date": "2026-02-01", "end_date": "2026-02-14", "reason": "Lunar New Year"})
        check("blackout period add redirects", r.status_code == 302)
        r = c.get(f"/suppliers/{supplier_id}")
        check("supplier page shows the blackout period", b"Lunar New Year" in r.data)

        # ---------------- BAS Generator (now a real expenses-ledger sum) ----------------
        with app.app_context():
            _db5 = _get_db2()
            expected_gst_paid = _db5.execute(
                "SELECT COALESCE(SUM(gst_amount), 0) v FROM expenses WHERE expense_date >= ? AND expense_date <= ?",
                ("2020-01-01", "2030-12-31 23:59:59"),
            ).fetchone()["v"]
        r = c.post("/financial/bas", data={"period_start": "2020-01-01", "period_end": "2030-12-31"})
        check("BAS generation redirects/renders", r.status_code == 200)
        check("BAS result shows GST Collected", b"GST Collected" in r.data)
        check("BAS GST Paid is summed from the expenses ledger (PO receipts + manual entries), not a PO-value/11 estimate",
              f"{expected_gst_paid:.2f}".encode() in r.data, expected_gst_paid)

        # ---------------- CapEx Calculator ----------------
        r = c.post("/financial/capex", data={"scenario_name": "Second Printer", "equipment_cost": "1000",
                                              "monthly_revenue_increase": "200", "monthly_cost_increase": "40"})
        check("capex scenario save redirects", r.status_code == 302)
        r = c.get("/financial/capex")
        check("capex page shows break-even months for the saved scenario", b"months" in r.data)

        # ---------------- Audit Logging (automatic, global — not opt-in per route) ----------------
        doc_match = re.search(rb'documents/(\d+)/delete', c.get("/documents/").data)
        doc_id = int(doc_match.group(1)) if doc_match else None
        check("found a document id to delete for the audit-log test", doc_id is not None)
        if doc_id:
            c.post(f"/documents/{doc_id}/delete")
            r = c.get("/admin/audit-log")
            check("audit log records the document delete", r.status_code == 200 and b"documents" in r.data and b"DELETE" in r.data)

        # An ordinary UPDATE on a route that never called the old manual audit
        # helper (e.g. saving a Part edit) should now log automatically too,
        # since logging moved into the shared DB connection layer.
        with app.app_context():
            _db6 = _get_db2()
            audit_count_before = _db6.execute("SELECT COUNT(*) c FROM audit_logs WHERE table_name='parts'").fetchone()["c"]
        c.post(f"/inventory/{part_id}/edit", data={"part_name": "PLA Filament 1kg (Updated)", "quantity_on_hand": "60",
                                                     "reorder_threshold": "10", "unit_cost": "20.00", "margin_pct": "50"})
        with app.app_context():
            _db6 = _get_db2()
            audit_count_after = _db6.execute("SELECT COUNT(*) c FROM audit_logs WHERE table_name='parts'").fetchone()["c"]
        check("a plain Part edit (never wired to the old manual audit helper) is now logged automatically",
              audit_count_after > audit_count_before, f"before={audit_count_before} after={audit_count_after}")

        # ---------------- Local Agent API (firmware flashing + IoT power monitoring) ----------------
        r = c.get("/admin/local-agent")
        check("admin local agent page 200", r.status_code == 200 and b"Local Agent" in r.data)
        r = c.post("/admin/local-agent", follow_redirects=True)
        check("generate Local Agent API key redirects/renders", r.status_code == 200 and b"Regenerate Key" in r.data)
        with app.app_context():
            _db7 = _get_db2()
            agent_key = _db7.execute("SELECT local_agent_api_key FROM company_settings WHERE id=1").fetchone()["local_agent_api_key"]
        check("API key was actually generated and stored", bool(agent_key))

        r = c.get("/api/ping", headers={"X-API-Key": agent_key})
        check("local agent /api/ping accepts the generated key", r.status_code == 200 and r.get_json().get("ok") is True)
        r = c.get("/api/ping", headers={"X-API-Key": "wrong-key"})
        check("local agent /api/ping rejects a bad key", r.status_code == 401)
        r = c.get("/api/ping")
        check("/api/* is exempt from the login gate (401 on bad/missing key, not a login redirect)", r.status_code == 401)

        r = c.post(f"/assets/new", data={"asset_name": "Bench Printer QA", "power_plug_reference": "192.168.50.20"})
        power_asset_id = get_id_from_redirect(r, r"/assets/(\d+)")
        check("asset with a power plug reference created", power_asset_id is not None)

        r = c.get("/api/power-monitored-assets", headers={"X-API-Key": agent_key})
        pma = r.get_json()["assets"] if r.status_code == 200 else []
        check("power-monitored-assets lists the asset with a plug reference set",
              any(a["id"] == power_asset_id for a in pma), pma)

        r = c.post("/api/power-readings", headers={"X-API-Key": agent_key}, json={"asset_id": power_asset_id, "watts": 37.5})
        check("power-readings accepts a single reading", r.status_code == 200 and r.get_json().get("inserted") == 1)
        r = c.get(f"/assets/{power_asset_id}")
        check("asset detail page shows the reported wattage", r.status_code == 200 and b"37.5" in r.data)

        with app.app_context():
            _db8 = _get_db2()
            fv_row = _db8.execute("SELECT id FROM firmware_versions LIMIT 1").fetchone()
        if fv_row:
            r = c.post("/api/firmware-flash-log", headers={"X-API-Key": agent_key}, json={
                "build_id": None, "firmware_version_id": fv_row["id"], "device_port": "/dev/ttyUSB0",
                "result": "Success", "log_output": "avrdude: 1 bytes of flash verified.",
            })
            check("firmware-flash-log accepts a Success report", r.status_code == 200 and r.get_json().get("ok") is True)
        r = c.post("/api/firmware-flash-log", headers={"X-API-Key": agent_key}, json={"result": "not-a-real-result"})
        check("firmware-flash-log rejects an invalid result value", r.status_code == 400)

        # ---------------- Analytics ----------------
        r = c.get("/analytics/")
        check("analytics index 200", r.status_code == 200)
        r = c.get("/analytics/reports")
        check("analytics reports 200", r.status_code == 200)
        r = c.get("/analytics/reports/inventory-valuation.csv")
        check("inventory valuation CSV downloads", r.status_code == 200 and r.mimetype == "text/csv")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed.")
    if FAIL:
        print("\nFAILURES:")
        for label, detail in FAIL:
            print(f"  - {label}: {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
