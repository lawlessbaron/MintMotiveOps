-- MintMotive Ops database schema (SQLite)
PRAGMA foreign_keys = ON;

-- =========================================================================
-- Company / Admin singleton + config tables
-- =========================================================================

CREATE TABLE company_settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),           -- singleton row
    company_name TEXT DEFAULT 'Mint Motive Solutions',
    tagline TEXT,
    show_company_name INTEGER NOT NULL DEFAULT 1,
    show_tagline INTEGER NOT NULL DEFAULT 1,
    abn TEXT,
    address TEXT,
    logo_path TEXT,
    default_currency TEXT DEFAULT 'AUD',
    default_margin_pct REAL DEFAULT 40.0,
    default_gst_rate_pct REAL DEFAULT 10.0,
    default_client_payment_term_id INTEGER REFERENCES client_payment_terms(id) ON DELETE SET NULL,
    default_supplier_payment_term_id INTEGER REFERENCES supplier_payment_terms(id) ON DELETE SET NULL,
    invoice_reminder_days INTEGER DEFAULT 7,
    labor_rate_per_hour REAL DEFAULT 45.0,
    -- Shared secret the local hardware agent (firmware flashing + IoT power
    -- monitoring — runs on the workshop PC, see local_agent/) sends as the
    -- X-API-Key header on its POSTs to /api/*. Generated on first use from
    -- Administration > Local Agent; regenerating it invalidates the old key.
    local_agent_api_key TEXT,
    notes TEXT,
    -- Packing Lists & Reminders: which fields print on packing/customs PDFs
    packing_include_weight INTEGER DEFAULT 1,
    packing_include_dimensions INTEGER DEFAULT 1,
    packing_include_value INTEGER DEFAULT 1,
    packing_include_customs_description INTEGER DEFAULT 1,
    packing_include_hs_code INTEGER DEFAULT 1,
    packing_include_origin_country INTEGER DEFAULT 1,
    -- Appearance: 9 colors x 2 modes, all user-editable, pre-filled with brand defaults
    light_page_bg TEXT DEFAULT '#F6EED9',
    light_card_bg TEXT DEFAULT '#FFFFFF',
    light_text_primary TEXT DEFAULT '#1E2124',
    light_text_secondary TEXT DEFAULT '#494949',
    light_accent TEXT DEFAULT '#9EC4B5',
    light_border TEXT DEFAULT '#494949',
    light_sidebar_bg TEXT DEFAULT '#1E2124',
    light_sidebar_text TEXT DEFAULT '#F6EED9',
    light_text_on_accent TEXT DEFAULT '#1E2124',
    dark_page_bg TEXT DEFAULT '#1E2124',
    dark_card_bg TEXT DEFAULT '#494949',
    dark_text_primary TEXT DEFAULT '#F6EED9',
    dark_text_secondary TEXT DEFAULT '#C9C9C9',
    dark_accent TEXT DEFAULT '#9EC4B5',
    dark_border TEXT DEFAULT '#6A6A6A',
    dark_sidebar_bg TEXT DEFAULT '#000000',
    dark_sidebar_text TEXT DEFAULT '#F6EED9',
    dark_text_on_accent TEXT DEFAULT '#1E2124',
    -- Stripe/SMTP set from Administration > Integrations instead of an
    -- environment variable. Env vars always take priority when set (see
    -- stripe_client.py/email_client.py) — these are the fallback for
    -- anyone who'd rather not touch their host's environment variables.
    -- Secrets are encrypted at rest (app/crypto_utils.py); host/port/
    -- user/from aren't secret so are stored plain.
    stripe_secret_key_encrypted TEXT,
    stripe_webhook_secret_encrypted TEXT,
    smtp_host TEXT,
    smtp_port INTEGER,
    smtp_user TEXT,
    smtp_password_encrypted TEXT,
    smtp_from TEXT
);

CREATE TABLE numbering_sequences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_name TEXT UNIQUE NOT NULL,   -- Part, Supplier, Kit, Sales Order, Purchase Order, Quote, Invoice, Build
    prefix TEXT DEFAULT '',
    next_number INTEGER NOT NULL DEFAULT 1,
    padding_length INTEGER NOT NULL DEFAULT 6,
    notes TEXT
);

CREATE TABLE integration_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    integration_name TEXT UNIQUE NOT NULL,  -- e.g. Shopify, Stripe
    status TEXT NOT NULL DEFAULT 'Inactive' CHECK (status IN ('Active','Inactive','Error')),
    connection_reference TEXT,
    last_sync_at TEXT,
    last_sync_result TEXT,
    notes TEXT
);

CREATE TABLE email_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT UNIQUE NOT NULL,  -- Shipping Notification, Build Complete, Quote Email, Invoice Email, Invoice Overdue Reminder
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

-- =========================================================================
-- Reference / lookup tables (end-user editable, Name + Active)
-- =========================================================================

CREATE TABLE part_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    default_margin_pct REAL
);

CREATE TABLE kit_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    default_margin_pct REAL
);

CREATE TABLE asset_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE document_types (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE supplier_payment_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE client_payment_terms (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE order_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT CHECK (type IN ('Parts Storage','Finished Kit Storage','Workstation')),
    -- Gridfinity bin coordinates: a location that IS a specific bin in a
    -- printed Gridfinity baseplate/drawer can record which baseplate and
    -- its (x,y) cell within it — drives the visual grid map and the
    -- serpentine (row-major, alternating direction) pick-path ordering on
    -- Batch Production Run pick lists. All optional — a location that
    -- isn't a Gridfinity bin (a shelf, a workstation) just leaves these null.
    baseplate_name TEXT,
    grid_x INTEGER,
    grid_y INTEGER
);

CREATE TABLE countries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    country_name TEXT UNIQUE NOT NULL,
    iso_code TEXT,
    default_import_duty_rate_pct REAL,
    gst_tax_note TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE harmonised_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    description TEXT,
    default_duty_rate_pct REAL,
    notes TEXT
);

CREATE TABLE customs_agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    company TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    services TEXT,
    notes TEXT
);

CREATE TABLE shipping_carriers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carrier_name TEXT NOT NULL,
    account_reference TEXT,
    notes TEXT
);

CREATE TABLE shipping_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    carrier_id INTEGER NOT NULL REFERENCES shipping_carriers(id) ON DELETE RESTRICT,
    destination_country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE RESTRICT,
    service_level TEXT,
    base_fee REAL DEFAULT 0,
    fee_per_kg REAL DEFAULT 0,
    estimated_transit_days INTEGER
);

CREATE TABLE sticker_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT NOT NULL,
    material TEXT CHECK (material IN ('Carbon Vinyl','Printable Paper','Clear/Waterproof','Other')),
    width_mm REAL,
    height_mm REAL,
    notes TEXT
);

-- =========================================================================
-- Suppliers, Parts, Sourcing Prospects
-- =========================================================================

CREATE TABLE suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name TEXT NOT NULL,
    supplier_code TEXT UNIQUE,
    contact_name TEXT,
    email TEXT,
    phone TEXT,
    website TEXT,
    address TEXT,
    payment_term_id INTEGER REFERENCES supplier_payment_terms(id) ON DELETE SET NULL,
    tax_business_number TEXT,
    currency TEXT DEFAULT 'AUD',
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Inactive','On Hold')),
    external_system_code TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_name TEXT NOT NULL,
    part_number TEXT UNIQUE,
    product_image_path TEXT,
    category_id INTEGER REFERENCES part_categories(id) ON DELETE SET NULL,
    quantity_on_hand INTEGER NOT NULL DEFAULT 0,
    quantity_reserved INTEGER NOT NULL DEFAULT 0,   -- system-managed only
    reorder_threshold INTEGER NOT NULL DEFAULT 0,
    unit_cost REAL NOT NULL DEFAULT 0,
    margin_pct REAL NOT NULL DEFAULT 0,
    preferred_supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    external_system_code TEXT,
    harmonised_code_id INTEGER REFERENCES harmonised_codes(id) ON DELETE SET NULL,
    country_of_origin_id INTEGER REFERENCES countries(id) ON DELETE SET NULL,
    weight_kg REAL,
    length_cm REAL,
    width_cm REAL,
    height_cm REAL,
    bin_location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    label_link_type TEXT DEFAULT 'Internal Record' CHECK (label_link_type IN ('Internal Record','Custom URL')),
    label_url TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- Available Quantity = quantity_on_hand - quantity_reserved (computed in application/view layer)
-- Sell Price = unit_cost * (1 + margin_pct/100) (computed in application/view layer)

CREATE TABLE supplier_blackout_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    reason TEXT   -- e.g. Lunar New Year, factory shutdown
);

CREATE TABLE part_suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE CASCADE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
    supplier_part_number TEXT,
    supplier_cost REAL,
    lead_time_days INTEGER,
    source_url TEXT,
    preferred INTEGER NOT NULL DEFAULT 0,
    UNIQUE (part_id, supplier_id)
);

CREATE TABLE sourcing_prospects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prospect_name TEXT NOT NULL,
    product_image_path TEXT,
    source_link TEXT,
    source_platform TEXT CHECK (source_platform IN ('Alibaba','AliExpress','1688','Amazon','Direct Supplier Website','Other')),
    supplier_name_listed TEXT,
    linked_supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    quoted_unit_price REAL,
    currency TEXT DEFAULT 'AUD',
    minimum_order_quantity INTEGER,
    lead_time_days INTEGER,
    potential_category_id INTEGER REFERENCES part_categories(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'Researching' CHECK (status IN ('Researching','Sample Requested','Sample Received','Approved','Rejected','On Hold')),
    notes TEXT,
    converted_to_part_id INTEGER REFERENCES parts(id) ON DELETE SET NULL,
    date_added TEXT DEFAULT CURRENT_TIMESTAMP,
    last_reviewed_date TEXT
);

-- =========================================================================
-- Kits, BOM, Builds, Assets
-- =========================================================================

CREATE TABLE kits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_name TEXT NOT NULL,
    sku TEXT UNIQUE,
    category_id INTEGER REFERENCES kit_categories(id) ON DELETE SET NULL,
    screen_size TEXT,
    revision TEXT,
    version TEXT,
    status TEXT NOT NULL DEFAULT 'In Development' CHECK (status IN ('In Development','Active','Discontinued')),
    kit_image_path TEXT,
    project_name TEXT,
    drive_directory TEXT,
    primary_cad_file_link TEXT,
    description TEXT,
    margin_pct REAL NOT NULL DEFAULT 0,
    freight_included_in_price INTEGER NOT NULL DEFAULT 0,
    estimated_freight_allowance REAL DEFAULT 0,
    shopify_product_id TEXT,
    shopify_handle TEXT,
    harmonised_code_id INTEGER REFERENCES harmonised_codes(id) ON DELETE SET NULL,
    weight_kg REAL, length_cm REAL, width_cm REAL, height_cm REAL,
    customer_label_link_type TEXT DEFAULT 'Custom URL' CHECK (customer_label_link_type IN ('Shopify Help Page','Document Download','Custom URL')),
    customer_label_url TEXT,
    -- A sub-assembly is a Kit that isn't sold directly — it's built once and
    -- then consumed as a BOM component by one or more "final" Kits (see
    -- kit_parts.component_kit_id below). Sellable pickers (Sales Order/
    -- Quote/Invoice line items) filter this out; the Kits list still shows
    -- it, tagged, since it's built and tracked the same way.
    is_subassembly INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- Total Part Cost, Sell Price computed in application layer from kit_parts + parts.unit_cost
-- (recursively, through any component_kit_id sub-assembly levels — see app/db.py kit_total_part_cost)

CREATE TABLE kit_parts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
    -- A BOM line is EITHER a raw Part OR another Kit acting as a
    -- sub-assembly — exactly one of these two is set, enforced below.
    -- This is what makes the BOM multi-level: a kit's own BOM can include
    -- other kits, to any depth.
    part_id INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    component_kit_id INTEGER REFERENCES kits(id) ON DELETE RESTRICT,
    quantity_required INTEGER NOT NULL DEFAULT 1,
    CHECK ((part_id IS NOT NULL AND component_kit_id IS NULL) OR (part_id IS NULL AND component_kit_id IS NOT NULL)),
    CHECK (component_kit_id IS NULL OR component_kit_id <> kit_id),
    UNIQUE (kit_id, part_id),
    UNIQUE (kit_id, component_kit_id)
);

CREATE TABLE firmware_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
    version_label TEXT NOT NULL,        -- e.g. "v1.3.2"
    file_path TEXT,                     -- uploaded .hex/.bin/.uf2, etc.
    release_notes TEXT,
    released_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (kit_id, version_label)
);

-- Engineering Change Orders: every approved edit to a kit's BOM is recorded
-- here with a full JSON snapshot of kit_parts at that moment, so past
-- revisions can always be reconstructed even though kit_parts itself only
-- ever holds the CURRENT BOM.
CREATE TABLE kit_ecos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
    eco_number TEXT UNIQUE,
    description TEXT NOT NULL,
    bom_snapshot TEXT NOT NULL,   -- JSON array: BOM lines as they stood at the time of this ECO
    status TEXT NOT NULL DEFAULT 'Approved' CHECK (status IN ('Draft','Approved','Superseded')),
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Routings: the ordered build/assembly steps for a Kit, with an estimated
-- time each — the basis for real labor-time tracking on Builds below.
CREATE TABLE routing_steps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL DEFAULT 1,
    step_name TEXT NOT NULL,
    instructions TEXT,
    estimated_minutes REAL DEFAULT 0,
    UNIQUE (kit_id, step_number)
);

CREATE TABLE assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_name TEXT NOT NULL,
    asset_type_id INTEGER REFERENCES asset_types(id) ON DELETE SET NULL,
    serial_number TEXT,
    purchase_date TEXT,
    purchase_cost REAL,
    location_id INTEGER REFERENCES locations(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'In Service' CHECK (status IN ('In Service','Under Maintenance','Retired')),
    maintenance_notes TEXT,
    -- IoT power monitoring: an identifier the local hardware agent uses to
    -- know which smart plug on the workshop LAN corresponds to this asset
    -- (its local IP or hostname — e.g. a Tasmota/Shelly plug address).
    -- Blank means this asset isn't power-monitored.
    power_plug_reference TEXT
);

CREATE TABLE power_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset_id INTEGER NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    watts REAL NOT NULL,
    recorded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- Clients, Addresses, Contacts
-- =========================================================================

CREATE TABLE clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_name TEXT NOT NULL,
    company TEXT,
    email TEXT,
    phone TEXT,
    client_type TEXT NOT NULL DEFAULT 'Individual' CHECK (client_type IN ('Individual','Business')),
    payment_term_id INTEGER REFERENCES client_payment_terms(id) ON DELETE SET NULL,
    client_since TEXT,
    shopify_customer_id TEXT,
    status TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Inactive')),
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE client_addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    address_label TEXT,
    address_line1 TEXT,
    address_line2 TEXT,
    city TEXT,
    state_region TEXT,
    postcode TEXT,
    country_id INTEGER NOT NULL REFERENCES countries(id) ON DELETE RESTRICT,
    is_default_shipping INTEGER NOT NULL DEFAULT 0,
    is_default_billing INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

CREATE TABLE client_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_name TEXT NOT NULL,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    role_title TEXT,
    email TEXT,
    phone TEXT,
    is_primary_contact INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);

-- =========================================================================
-- Sales Orders / Purchase Orders / Quotes / Invoices
-- =========================================================================

CREATE TABLE sales_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_number TEXT UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    source_id INTEGER REFERENCES order_sources(id) ON DELETE SET NULL,
    shopify_order_id TEXT,
    order_date TEXT DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'New' CHECK (status IN ('New','In Production','Ready to Ship','Shipped','Completed','Cancelled')),
    shipping_address_id INTEGER REFERENCES client_addresses(id) ON DELETE SET NULL,
    shipping_address_override TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE sales_order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sales_order_id INTEGER NOT NULL REFERENCES sales_orders(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL DEFAULT 'Kit' CHECK (item_type IN ('Kit','Part','Custom')),
    kit_id INTEGER REFERENCES kits(id) ON DELETE RESTRICT,
    part_id INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    description TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0
);
-- line_total = quantity * unit_price (computed)

CREATE TABLE purchase_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    po_number TEXT UNIQUE,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE RESTRICT,
    order_date TEXT DEFAULT CURRENT_TIMESTAMP,
    expected_delivery_date TEXT,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Sent','Confirmed','Partially Received','Received','Cancelled')),
    closed_date TEXT,
    reopened INTEGER NOT NULL DEFAULT 0,
    reopened_notes TEXT,
    customs_agent_id INTEGER REFERENCES customs_agents(id) ON DELETE SET NULL,
    duty_payment_status TEXT NOT NULL DEFAULT 'Not Applicable' CHECK (duty_payment_status IN ('Not Applicable','Prepaid by Agent','Owing','Paid')),
    estimated_duty_owed REAL,
    actual_duty_paid REAL,
    -- Landed cost distribution: actual freight/duty entered once on receipt,
    -- spread across the PO's lines by value and folded into each part's
    -- moving-average unit_cost. received_date drives Supplier Reliability
    -- (days late vs expected_delivery_date).
    actual_freight_paid REAL,
    landed_cost_applied INTEGER NOT NULL DEFAULT 0,
    received_date TEXT,
    notes TEXT,
    -- Spending limits & approvals: set when the PO is created; checked
    -- against the requester's users.spending_limit the moment someone
    -- tries to move it out of Draft (i.e. actually commit it to the
    -- supplier) — see purchase_orders.update_status.
    requested_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approval_status TEXT NOT NULL DEFAULT 'Not Required' CHECK (approval_status IN ('Not Required','Pending','Approved','Rejected')),
    approved_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    approved_at TEXT,
    approval_notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE purchase_order_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    purchase_order_id INTEGER NOT NULL REFERENCES purchase_orders(id) ON DELETE CASCADE,
    part_id INTEGER NOT NULL REFERENCES parts(id) ON DELETE RESTRICT,
    quantity_ordered INTEGER NOT NULL DEFAULT 0,
    quantity_received INTEGER NOT NULL DEFAULT 0,
    unit_cost REAL NOT NULL DEFAULT 0
);

-- General expenses ledger — the real source for the BAS Generator's GST
-- Paid figure (replacing the old PO-value/11 approximation). A row with
-- source='Purchase Order' is auto-filed when that PO is fully received
-- (its GST estimated the same 10%-inclusive way as before, but now it's
-- an editable, itemized ledger line instead of a silent formula); every
-- other expense (rent, software, tools, freight you pay directly, etc.)
-- is filed manually so BAS finally sees the whole picture, not just stock.
CREATE TABLE expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_date TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    category TEXT NOT NULL DEFAULT 'Other' CHECK (category IN ('Stock Purchases','Rent','Software & Subscriptions','Shipping & Freight','Tools & Equipment','Utilities','Professional Services','Other')),
    description TEXT,
    supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    amount_ex_gst REAL NOT NULL DEFAULT 0,
    gst_amount REAL NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'Manual' CHECK (source IN ('Manual','Purchase Order')),
    related_purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_number TEXT UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    quote_date TEXT DEFAULT CURRENT_TIMESTAMP,
    expiry_date TEXT,
    payment_term_id INTEGER REFERENCES client_payment_terms(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Sent','Accepted','Declined','Expired')),
    destination_country_id INTEGER REFERENCES countries(id) ON DELETE SET NULL,
    shipping_duty_terms TEXT NOT NULL DEFAULT 'Domestic' CHECK (shipping_duty_terms IN ('Domestic','Free Freight Included','Freight Charged Separately','DDP','DAP')),
    display_currency TEXT NOT NULL DEFAULT 'AUD',
    exchange_rate REAL NOT NULL DEFAULT 1,
    estimated_freight REAL DEFAULT 0,
    estimated_duty REAL DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE quote_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    quote_id INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL DEFAULT 'Kit' CHECK (item_type IN ('Kit','Part','Custom')),
    kit_id INTEGER REFERENCES kits(id) ON DELETE RESTRICT,
    part_id INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    description TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0
);

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_number TEXT UNIQUE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    related_sales_order_id INTEGER REFERENCES sales_orders(id) ON DELETE SET NULL,
    related_quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
    invoice_date TEXT DEFAULT CURRENT_TIMESTAMP,
    due_date TEXT,
    payment_term_id INTEGER REFERENCES client_payment_terms(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Sent','Paid','Overdue','Cancelled')),
    destination_country_id INTEGER REFERENCES countries(id) ON DELETE SET NULL,
    shipping_duty_terms TEXT NOT NULL DEFAULT 'Domestic' CHECK (shipping_duty_terms IN ('Domestic','Free Freight Included','Freight Charged Separately','DDP','DAP')),
    display_currency TEXT NOT NULL DEFAULT 'AUD',
    exchange_rate REAL NOT NULL DEFAULT 1,
    estimated_freight REAL DEFAULT 0,
    estimated_duty REAL DEFAULT 0,
    notes TEXT,
    public_token TEXT UNIQUE,           -- unique link token for the public pay-now page
    stripe_checkout_session_id TEXT,
    paid_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE invoice_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    item_type TEXT NOT NULL DEFAULT 'Kit' CHECK (item_type IN ('Kit','Part','Custom')),
    kit_id INTEGER REFERENCES kits(id) ON DELETE RESTRICT,
    part_id INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    description TEXT,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price REAL NOT NULL DEFAULT 0
);

-- =========================================================================
-- Batch Production Runs (defined before Builds: a Build can belong to one)
-- =========================================================================

CREATE TABLE batch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_number TEXT UNIQUE,
    kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'Planned' CHECK (status IN ('Planned','Picking','In Production','Complete','Cancelled')),
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- Builds
-- =========================================================================

CREATE TABLE builds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_number TEXT UNIQUE,
    kit_id INTEGER NOT NULL REFERENCES kits(id) ON DELETE RESTRICT,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    linked_sales_order_id INTEGER REFERENCES sales_orders(id) ON DELETE SET NULL,
    related_quote_id INTEGER REFERENCES quotes(id) ON DELETE SET NULL,
    related_invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,
    batch_run_id INTEGER REFERENCES batch_runs(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'Queued' CHECK (status IN ('Queued','Printing','Assembly','QC','Ready to Ship','Shipped','Complete')),
    serial_number TEXT UNIQUE,   -- auto-generated (Numbering: "Serial") but editable
    firmware_version_id INTEGER REFERENCES firmware_versions(id) ON DELETE SET NULL,
    build_photos TEXT,          -- comma-separated file paths / JSON array
    start_date TEXT,
    completed_date TEXT,
    shipping_carrier_id INTEGER REFERENCES shipping_carriers(id) ON DELETE SET NULL,
    tracking_number TEXT,
    ship_date TEXT,
    stock_reserved INTEGER NOT NULL DEFAULT 0,   -- internal flag: has this build's BOM been reserved yet
    stock_consumed INTEGER NOT NULL DEFAULT 0,   -- internal flag: has this build's BOM been consumed yet
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Build-level BOM overrides (CPQ): a specific Build can substitute a
-- different Part/Sub-Assembly for one of its Kit's normal BOM lines —
-- e.g. a client wants a custom knob or a premium screen on this one unit.
-- Stock reservation/consumption logic reads these overrides in preference
-- to the Kit's standard kit_parts BOM.
CREATE TABLE build_bom_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id INTEGER NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    original_kit_part_id INTEGER REFERENCES kit_parts(id) ON DELETE SET NULL,
    substitute_part_id INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    substitute_component_kit_id INTEGER REFERENCES kits(id) ON DELETE RESTRICT,
    quantity_required INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    CHECK ((substitute_part_id IS NOT NULL AND substitute_component_kit_id IS NULL) OR (substitute_part_id IS NULL AND substitute_component_kit_id IS NOT NULL))
);

-- Per-build time logs against the Kit's routing steps — real labor time,
-- multiplied by company_settings.labor_rate_per_hour, for true COGS.
CREATE TABLE build_step_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id INTEGER NOT NULL REFERENCES builds(id) ON DELETE CASCADE,
    routing_step_id INTEGER NOT NULL REFERENCES routing_steps(id) ON DELETE RESTRICT,
    started_at TEXT,
    completed_at TEXT,
    actual_minutes REAL,
    notes TEXT,
    UNIQUE (build_id, routing_step_id)
);

-- RMAs: a returned Build torn down into its components, each disposed of
-- as Scrap or Restock (Restock adds the quantity back to parts.quantity_on_hand).
CREATE TABLE rmas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rma_number TEXT UNIQUE,
    build_id INTEGER REFERENCES builds(id) ON DELETE SET NULL,
    client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'Received' CHECK (status IN ('Received','Teardown Complete','Resolved','Closed')),
    resolution TEXT CHECK (resolution IN ('Repaired','Replaced','Refunded','Scrapped')),
    received_date TEXT DEFAULT CURRENT_TIMESTAMP,
    resolved_date TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE rma_teardown_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rma_id INTEGER NOT NULL REFERENCES rmas(id) ON DELETE CASCADE,
    part_id INTEGER REFERENCES parts(id) ON DELETE RESTRICT,
    component_kit_id INTEGER REFERENCES kits(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL DEFAULT 1,
    disposition TEXT NOT NULL DEFAULT 'Scrap' CHECK (disposition IN ('Scrap','Restock')),
    notes TEXT,
    CHECK ((part_id IS NOT NULL AND component_kit_id IS NULL) OR (part_id IS NULL AND component_kit_id IS NOT NULL))
);

-- Firmware flashing history — written by the browser page (Kit Firmware
-- Versions / Build detail) immediately after the local hardware agent
-- (local_agent/flasher_agent.py, running on the same workshop PC as the
-- USB-connected board) reports success or failure back to it.
CREATE TABLE firmware_flash_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id INTEGER REFERENCES builds(id) ON DELETE SET NULL,
    firmware_version_id INTEGER REFERENCES firmware_versions(id) ON DELETE SET NULL,
    device_port TEXT,
    result TEXT NOT NULL CHECK (result IN ('Success','Failed')),
    log_output TEXT,
    flashed_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- Documents, Quick Links
-- =========================================================================

CREATE TABLE documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_name TEXT NOT NULL,
    document_type_id INTEGER REFERENCES document_types(id) ON DELETE SET NULL,
    file_path TEXT,
    related_client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    related_supplier_id INTEGER REFERENCES suppliers(id) ON DELETE SET NULL,
    related_purchase_order_id INTEGER REFERENCES purchase_orders(id) ON DELETE SET NULL,
    related_sales_order_id INTEGER REFERENCES sales_orders(id) ON DELETE SET NULL,
    related_kit_id INTEGER REFERENCES kits(id) ON DELETE SET NULL,
    related_build_id INTEGER REFERENCES builds(id) ON DELETE SET NULL,
    upload_date TEXT DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

CREATE TABLE quick_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    link_name TEXT NOT NULL,
    link_type TEXT CHECK (link_type IN ('Google Review Page','Help Document','Landing Page','Video','Custom URL')),
    url TEXT NOT NULL,
    related_part_id INTEGER REFERENCES parts(id) ON DELETE SET NULL,
    related_kit_id INTEGER REFERENCES kits(id) ON DELETE SET NULL,
    related_client_id INTEGER REFERENCES clients(id) ON DELETE SET NULL,
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT
);

-- =========================================================================
-- Users (simple single/multi-user auth)
-- =========================================================================

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'Owner' CHECK (role IN ('Owner','Workshop')),
    -- Per-user override: a Workshop account with this set can view
    -- Analytics & Reports (otherwise Owner-only) without being made a full
    -- Owner. Owners always have access regardless of this flag.
    can_view_analytics INTEGER NOT NULL DEFAULT 0,
    -- NULL = no limit (every Owner, and any Workshop account an Owner
    -- hasn't restricted). A number caps the $ value of a Purchase Order
    -- this user can send to a supplier without Owner approval first —
    -- see purchase_orders.approval_status below.
    spending_limit REAL,
    -- Comma-separated widget ids this user has hidden from Analytics —
    -- NULL/empty means every widget shows (the default). Per-user, not
    -- company-wide, since which numbers matter varies by role.
    hidden_analytics_widgets TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Self-service "forgot password" one-time codes (emailed — see
-- app/email_client.py and app/blueprints/auth.py). Never stores the raw
-- code, only a hash of it; expires_at + attempts enforce a short TTL and a
-- capped number of guesses instead of relying on the code's length alone.
CREATE TABLE password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Login rate limiting — every login POST logs one row here (success or
-- not); auth.login checks the count of recent failures for the submitted
-- email and for the client IP before even checking the password, and
-- blocks with neither DB row inserted nor password checked once either
-- threshold is hit. Deliberately keyed on the raw submitted email string,
-- not a user_id FK — a nonexistent email still needs to count toward its
-- own lockout, otherwise the lockout message itself would leak whether an
-- account exists.
CREATE TABLE login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    ip_address TEXT,
    success INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- =========================================================================
-- Financial / compliance
-- =========================================================================

-- Break-even calculator scenarios (equipment/CapEx vs. projected monthly impact)
CREATE TABLE capex_scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_name TEXT NOT NULL,
    equipment_cost REAL NOT NULL DEFAULT 0,
    monthly_revenue_increase REAL NOT NULL DEFAULT 0,
    monthly_cost_increase REAL NOT NULL DEFAULT 0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
-- Break-even (months) = equipment_cost / (monthly_revenue_increase - monthly_cost_increase) (computed in app layer)

-- Saved snapshots of generated BAS (Business Activity Statement) reports.
-- gst_paid_estimated is an APPROXIMATION: received PO line value / 11
-- (assumes 10%-inclusive GST on stock purchases) — there is no general
-- vendor-bills/expenses ledger yet to source real GST-paid figures from.
CREATE TABLE bas_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    gst_collected REAL NOT NULL DEFAULT 0,
    gst_paid_estimated REAL NOT NULL DEFAULT 0,
    net_gst_payable REAL NOT NULL DEFAULT 0,
    generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    notes TEXT
);

-- Best-effort audit trail for UPDATE/DELETE writes. Populated by a
-- heuristic wrapper (see app/db.py) rather than true row-level diffing —
-- there is no ORM/ORM-events layer to hook into, so table_name/record_id
-- are inferred from the SQL text and the last bound parameter.
CREATE TABLE audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    record_id INTEGER,
    action TEXT NOT NULL CHECK (action IN ('INSERT','UPDATE','DELETE')),
    changed_by TEXT,
    changed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    details TEXT
);

-- =========================================================================
-- Useful indexes
-- =========================================================================

CREATE INDEX idx_parts_category ON parts(category_id);
CREATE INDEX idx_kits_category ON kits(category_id);
CREATE INDEX idx_kit_parts_kit ON kit_parts(kit_id);
CREATE INDEX idx_kit_parts_part ON kit_parts(part_id);
CREATE INDEX idx_builds_kit ON builds(kit_id);
CREATE INDEX idx_builds_client ON builds(client_id);
CREATE INDEX idx_builds_status ON builds(status);
CREATE INDEX idx_sales_orders_client ON sales_orders(client_id);
CREATE INDEX idx_quotes_client ON quotes(client_id);
CREATE INDEX idx_invoices_client ON invoices(client_id);
CREATE INDEX idx_invoices_token ON invoices(public_token);
CREATE INDEX idx_client_addresses_client ON client_addresses(client_id);
CREATE INDEX idx_client_contacts_client ON client_contacts(client_id);
CREATE INDEX idx_kit_ecos_kit ON kit_ecos(kit_id);
CREATE INDEX idx_routing_steps_kit ON routing_steps(kit_id);
CREATE INDEX idx_batch_runs_kit ON batch_runs(kit_id);
CREATE INDEX idx_builds_batch_run ON builds(batch_run_id);
CREATE INDEX idx_build_bom_overrides_build ON build_bom_overrides(build_id);
CREATE INDEX idx_build_step_logs_build ON build_step_logs(build_id);
CREATE INDEX idx_rmas_build ON rmas(build_id);
CREATE INDEX idx_rmas_client ON rmas(client_id);
CREATE INDEX idx_rma_teardown_rma ON rma_teardown_lines(rma_id);
CREATE INDEX idx_supplier_blackout_supplier ON supplier_blackout_periods(supplier_id);
CREATE INDEX idx_audit_logs_table ON audit_logs(table_name, record_id);
CREATE INDEX idx_expenses_date ON expenses(expense_date);
CREATE INDEX idx_expenses_po ON expenses(related_purchase_order_id);
CREATE INDEX idx_firmware_flash_log_build ON firmware_flash_log(build_id);
CREATE INDEX idx_power_readings_asset ON power_readings(asset_id, recorded_at);
CREATE INDEX idx_locations_baseplate ON locations(baseplate_name);
