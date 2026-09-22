const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, BorderStyle, ShadingType,
  LevelFormat, PageBreak, TableOfContents, convertInchesToTwip,
  Footer, Header, PageNumber, TabStopType, TabStopPosition,
} = require("docx");
const fs = require("fs");

// ---------------------------------------------------------------------
// Brand palette (matches MintMotive Ops' own Appearance defaults)
// ---------------------------------------------------------------------
const TEAL = "9EC4B5";
const CHARCOAL = "494949";
const CARBON = "1E2124";
const EGGSHELL_HEX = "F6EED9";

// ---------------------------------------------------------------------
// Small helpers so the content below reads like content, not markup.
// ---------------------------------------------------------------------
function h1(text) {
  return new Paragraph({ text, heading: HeadingLevel.HEADING_1, spacing: { before: 400, after: 200 } });
}
function h2(text) {
  return new Paragraph({ text, heading: HeadingLevel.HEADING_2, spacing: { before: 320, after: 160 } });
}
function h3(text) {
  return new Paragraph({ text, heading: HeadingLevel.HEADING_3, spacing: { before: 240, after: 120 } });
}
function p(text, opts = {}) {
  return new Paragraph({
    children: [new TextRun({ text, ...opts })],
    spacing: { after: 160 },
  });
}
function pRich(runs) {
  return new Paragraph({ children: runs, spacing: { after: 160 } });
}
function bullet(text, level = 0) {
  return new Paragraph({
    text,
    numbering: { reference: "bullet-list", level },
    spacing: { after: 80 },
  });
}
const stepRefs = new Set();
function step(text, level = 0, ref = "step-list") {
  stepRefs.add(ref);
  return new Paragraph({
    text,
    numbering: { reference: ref, level },
    spacing: { after: 80 },
  });
}
function slugify(s) {
  return "step-" + s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}
function note(text) {
  return new Paragraph({
    children: [new TextRun({ text: "Note: ", bold: true, color: CHARCOAL }), new TextRun({ text, italics: true, color: CHARCOAL })],
    spacing: { before: 60, after: 200 },
    indent: { left: convertInchesToTwip(0.25) },
    border: { left: { style: BorderStyle.SINGLE, size: 12, color: TEAL, space: 8 } },
  });
}
function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

// A labeled field/definition line, e.g. "Status: ..." used for quick-reference tables.
function field(label, text) {
  return new Paragraph({
    children: [new TextRun({ text: label + ": ", bold: true }), new TextRun({ text })],
    spacing: { after: 80 },
  });
}

// ---------------------------------------------------------------------
// Cover page
// ---------------------------------------------------------------------
const cover = [
  new Paragraph({ text: "", spacing: { before: 1600 } }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "MintMotive Ops", bold: true, size: 64, color: CARBON })],
    spacing: { after: 200 },
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "User Guide", bold: true, size: 36, color: CHARCOAL })],
    spacing: { after: 400 },
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "The complete business operations system for Mint Motive Solutions", italics: true, size: 24, color: CHARCOAL })],
    spacing: { after: 100 },
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Clients & sales · Kits, builds & firmware · Inventory & purchasing · Warehouse · Financials · Administration", size: 20, color: CHARCOAL })],
    spacing: { after: 800 },
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "September 2026", size: 20, color: CHARCOAL })],
  }),
  pageBreak(),
];

// Hand-authored contents list (rather than a Word TOC field, which shows
// blank until the reader manually refreshes it) — a chapter/section
// structure that always renders correctly in Word, Google Docs, and
// LibreOffice with no extra step required.
function contentsEntry(text, level = 0) {
  return new Paragraph({
    children: [new TextRun({ text, bold: level === 0, size: level === 0 ? 24 : 21, color: level === 0 ? CARBON : CHARCOAL })],
    spacing: { before: level === 0 ? 160 : 0, after: level === 0 ? 40 : 60 },
    indent: { left: level === 0 ? 0 : convertInchesToTwip(0.3) },
  });
}
const CONTENTS_OUTLINE = [
  ["1. Getting Started", 0],
  ["1.1 Logging In · 1.2 Finding Your Way Around · 1.3 Search, Theme & Your Account", 1],
  ["2. Dashboard", 0],
  ["3. Sales Pipeline", 0],
  ["3.1 Clients · 3.2 Quotes · 3.3 Sales Orders · 3.4 Invoices & Payment", 1],
  ["4. Product & Production", 0],
  ["4.1 Kits & BOM · 4.2 ECOs · 4.3 Firmware & Flashing · 4.4 Routing & Operations", 1],
  ["4.5 Custom Builds (CPQ) · 4.6 Workshop Board · 4.7 Batch Runs & Gridfinity · 4.8 RMAs", 1],
  ["5. Inventory & Purchasing", 0],
  ["5.1 Inventory · 5.2 Suppliers · 5.3 Sourcing Prospects", 1],
  ["5.4 Purchase Orders & Receiving · 5.5 Landed Cost · 5.6 Procurement Queue", 1],
  ["6. Warehouse", 0],
  ["6.1 Locations & Gridfinity Setup · 6.2 Assets & Power Monitoring", 1],
  ["7. Insights & Financials", 0],
  ["7.1 Analytics · 7.2 Reports · 7.3 Expenses Ledger · 7.4 BAS Generator · 7.5 CapEx Calculator", 1],
  ["8. Tools", 0],
  ["8.1 Documents · 8.2 Labels & Quick Links", 1],
  ["9. Administration", 0],
  ["9.1 Overview · 9.2 Company · 9.3 Duties & Shipping · 9.4 Numbering · 9.5 Integrations", 1],
  ["9.6 Security · 9.7 Appearance · 9.8 Audit Log · 9.9 Local Agent", 1],
  ["10. Tips & Troubleshooting", 0],
  ["11. Local Agent Setup (Firmware Flashing & IoT Power Monitoring)", 0],
  ["11.1 One-Time Setup · 11.2 Flashing a Board · 11.3 Power Monitoring · 11.4 Troubleshooting", 1],
];
const contents = [
  h1("Contents"),
  ...CONTENTS_OUTLINE.map(([text, level]) => contentsEntry(text, level)),
  pageBreak(),
];

// ---------------------------------------------------------------------
// 1. Getting Started
// ---------------------------------------------------------------------
const gettingStarted = [
  h1("1. Getting Started"),
  p("MintMotive Ops is your team's single system for everything the business runs on day to day: sales, builds, inventory, purchasing, the warehouse, and the financial reporting that ties it together. It's server-hosted, so anyone on the team opens it from a browser — no installers, no per-machine setup (the one exception is the optional Local Agent for firmware flashing and power monitoring, covered in Chapter 11)."),

  h2("1.1 Logging In"),
  step("Open MintMotive Ops in your browser and go to the login page.", 0, "step-1-1"),
  step("Enter your email address and password.", 0, "step-1-1"),
  step("The first time you log in with an account an administrator created for you, change your password from Administration › Security.", 0, "step-1-1"),
  note("If you forget your password, ask an Owner-role user to reset it for you from Administration › Security — there's no self-service “forgot password” flow yet."),

  h2("1.2 Finding Your Way Around"),
  p("The sidebar on the left is organized into the areas you'll use most:"),
  bullet("Dashboard, Sales Orders, Clients, Quotes, Invoices, and Kits & Builds sit at the top level since they're used constantly."),
  bullet("Production groups the Workshop Board, Batch Runs, and RMAs — everything about turning parts into finished, shipped units."),
  bullet("Purchasing groups Purchase Orders, the Procurement Queue, and Sourcing Prospects."),
  bullet("Warehouse groups physical Locations and Assets."),
  bullet("Insights groups Analytics, Reports, the BAS Generator, Expenses, and the CapEx Calculator."),
  bullet("Tools groups Documents and Labels & Quick Links."),
  bullet("Administration sits by itself at the bottom — company-wide settings, users, numbering, integrations, branding, the audit log, and the Local Agent."),
  p("Click a grouped section's header (Production, Purchasing, Warehouse, Insights, Tools) to expand or collapse it; MintMotive Ops remembers which groups you left open."),

  h2("1.3 Search, Theme & Your Account"),
  bullet("The search box in the top bar searches across parts, kits, clients, and orders at once — use it instead of hunting through a module's list."),
  bullet("The “Theme” button switches between light and dark mode; your choice is remembered on that browser."),
  bullet("Your name and role (Owner or Workshop) are shown at the top right. Both roles currently have the same access — the role is there for reference and will support finer-grained permissions in a future update."),
  bullet("“Log out” ends your session."),
];

// ---------------------------------------------------------------------
// Generic module-section builder used for the bulk of the guide.
// ---------------------------------------------------------------------
function moduleSection(titleNum, title, purpose, subs) {
  const out = [h1(`${titleNum}. ${title}`), p(purpose)];
  for (const sub of subs) {
    out.push(h2(sub.heading));
    if (sub.intro) out.push(p(sub.intro));
    const ref = slugify(sub.heading); // each subsection's step list restarts at 1
    for (const item of sub.items || []) {
      if (item.type === "bullet") out.push(bullet(item.text, item.level || 0));
      else if (item.type === "step") out.push(step(item.text, item.level || 0, ref));
      else if (item.type === "sub") out.push(h3(item.text));
      else if (item.type === "note") out.push(note(item.text));
      else if (item.type === "p") out.push(p(item.text));
      else if (item.type === "field") out.push(field(item.label, item.text));
    }
  }
  return out;
}

// ---------------------------------------------------------------------
// 2. Dashboard
// ---------------------------------------------------------------------
const dashboard = [
  h1("2. Dashboard"),
  p("The Dashboard is the first thing you see after logging in — a real-time snapshot pulled straight from your actual records, not a mock-up. It shows open sales orders, active builds, unpaid invoices and the dollar amount outstanding, how many parts are at or below their reorder threshold, and your total client count, plus short lists of recent sales orders, active builds, and low-stock parts so you know what needs attention right now."),
];

// ---------------------------------------------------------------------
// 3. Sales Pipeline
// ---------------------------------------------------------------------
const salesPipeline = moduleSection(3, "Sales Pipeline", "Everything from a first client conversation through to a paid invoice lives in these four connected modules.", [
  {
    heading: "3.1 Clients",
    intro: "A client record holds contact details plus every address and contact person associated with them, and links out to every Quote, Sales Order, Invoice, and Build tied to that client.",
    items: [
      { type: "step", text: "Go to Clients › + New Client, fill in their details, and save." },
      { type: "step", text: "Open a client to add additional Addresses (billing/shipping) and Contacts (extra people at that company)." },
      { type: "bullet", text: "A client's detail page is your one-stop view of their history — use it before a call instead of piecing information together from other modules." },
    ],
  },
  {
    heading: "3.2 Quotes",
    intro: "Quotes use a live split-pane builder: edit line items on the left and see the formatted quote update in real time on the right, exactly as the client will see it.",
    items: [
      { type: "step", text: "Quotes › + New Quote, choose the client, and add line items (parts, kits, or freeform lines) with quantity and price." },
      { type: "step", text: "Set the destination country and shipping/duty terms if this is an international order — they drive the duty and freight estimate shown on the quote." },
      { type: "step", text: "Use “Email” to mark the quote as sent (draft review before sending is built in)." },
      { type: "step", text: "Once the client accepts, use “Convert to Invoice” to carry every line straight across — no retyping." },
    ],
  },
  {
    heading: "3.3 Sales Orders",
    intro: "A Sales Order tracks a confirmed order through fulfillment — it's the record that a Build gets linked back to.",
    items: [
      { type: "step", text: "Sales Orders › + New Sales Order, pick the client and order source, and add line items." },
      { type: "step", text: "Move the order through its statuses as it progresses; the order's detail page keeps a running total." },
    ],
  },
  {
    heading: "3.4 Invoices & Payment",
    intro: "Invoices are real GST tax invoices with exact totals — not estimates — and can carry a live Stripe-backed payment link.",
    items: [
      { type: "step", text: "Create an invoice directly, or convert an accepted Quote into one." },
      { type: "step", text: "“Generate Pay Link” creates a public payment page the client can pay from without logging in (requires Stripe to be configured — see Chapter 9.5)." },
      { type: "step", text: "“Email” prepares the invoice email for sending, the same reviewed-draft pattern used for quotes and build-complete notifications." },
      { type: "note", text: "Outbound email sending needs your own SMTP/email provider wired up on deployment — see DEPLOYMENT.md. Until then, MintMotive Ops prepares the draft and records it as sent so your workflow isn't blocked." },
    ],
  },
]);

// ---------------------------------------------------------------------
// 4. Product & Production
// ---------------------------------------------------------------------
const production = moduleSection(4, "Product & Production", "This is the heart of the shop floor: what a Kit is made of, how a Build moves from queued to shipped, firmware, labor time, batches, and returns.", [
  {
    heading: "4.1 Kits & Their Bill of Materials",
    intro: "A Kit is a sellable product definition — its BOM (bill of materials), category, margin, and every Build ever made from it.",
    items: [
      { type: "step", text: "Kits & Builds › + New Kit to define a new product." },
      { type: "step", text: "Add BOM lines: either a Part with a quantity, or another Kit as a sub-assembly (multi-level BOMs are fully supported — a kit's BOM can include another kit)." },
      { type: "step", text: "Use “+ Start New Build” on the Kit page to queue a new physical unit against that BOM." },
      { type: "bullet", text: "The Archive at the bottom of a Kit's page lists every completed build for that product." },
    ],
  },
  {
    heading: "4.2 Engineering Change Orders (ECOs)",
    intro: "Whenever a Kit's BOM changes, file an ECO to snapshot exactly what changed and why — past BOM revisions stay reconstructable even though the live BOM only ever shows the current version.",
    items: [
      { type: "step", text: "From a Kit's page, use “File ECO” and describe what changed and why." },
      { type: "bullet", text: "Every filed ECO is listed on the Kit page with its snapshot, so you always have a paper trail for BOM changes." },
    ],
  },
  {
    heading: "4.3 Firmware Versions & Flashing to a Device",
    intro: "Kits with onboard electronics can track firmware builds and flash them straight to a connected board from inside the app.",
    items: [
      { type: "step", text: "On a Kit's page, add a Firmware Version with a label (e.g. v1.3.2), the compiled firmware file, and release notes." },
      { type: "step", text: "Link a specific firmware version to a Build from the Build's detail page, so each physical unit records exactly what it shipped with." },
      { type: "step", text: "To actually flash a board, use the “Flash to Device” control on the Kit page (for a bench unit) or a Build's detail page (tied to that unit's record): pick the firmware version and click “⚡ Flash to Device.”" },
      { type: "note", text: "Flashing needs the Local Agent running on the same PC — a small helper program that does the real USB work, since a browser can't talk to a USB programmer directly. See Chapter 11 for full setup." },
      { type: "bullet", text: "Every attempt — success or failure, with the real avrdude output — is recorded in that Build's Flash History and in Administration › Local Agent." },
    ],
  },
  {
    heading: "4.4 Routing & Operations (Labor Time and True COGS)",
    intro: "Routing steps are the ordered assembly steps for a Kit, each with an estimated time. Builds log real time against each step, which rolls up into a build's true cost of goods — parts plus labor, not just parts.",
    items: [
      { type: "step", text: "On a Kit's page, add Routing Steps in order with a name, instructions, and an estimated time." },
      { type: "step", text: "On a Build's detail page, click Start on a step when work begins and Complete when it's done — actual minutes are calculated automatically (or enter them by hand)." },
      { type: "bullet", text: "The Build page shows both the accumulated labor cost and the true COGS (parts + labor), using your labor rate from Administration › Company." },
    ],
  },
  {
    heading: "4.5 Custom Builds (CPQ / BOM Overrides)",
    intro: "A single physical unit sometimes needs a substitution — a client-requested part swap, or an out-of-stock alternate — without changing the Kit's standard BOM for every other unit.",
    items: [
      { type: "step", text: "On a Build's detail page, add a BOM Override: either replace a specific BOM line with a substitute part or kit, or add an extra line entirely." },
      { type: "bullet", text: "Stock reservation and consumption automatically use this Build's effective BOM (the Kit's normal BOM with overrides applied), so inventory stays accurate even for one-off customizations." },
    ],
  },
  {
    heading: "4.6 Workshop Board (Kanban)",
    intro: "A drag-and-drop board of every active Build, organized by status — the fastest way to see what's in progress across the whole shop.",
    items: [
      { type: "step", text: "Open Production › Workshop Board." },
      { type: "step", text: "Drag a build card between columns to update its status — the change is saved immediately." },
    ],
  },
  {
    heading: "4.7 Batch Production Runs & Gridfinity Pick Lists",
    intro: "When you're building several units of the same Kit at once, a Batch Run spawns all those Builds together and gives you one combined pick list for the whole batch.",
    items: [
      { type: "step", text: "Production › Batch Runs › + New Batch Run, choose the Kit and quantity." },
      { type: "step", text: "The batch's Pick List totals every part needed across the whole batch, in the most efficient walking order." },
      { type: "bullet", text: "For parts stored in a named Gridfinity baseplate (see Chapter 6.1 for setup), the pick list shows a visual grid map of that baseplate with the needed cells highlighted and numbered in serpentine order — row by row, alternating direction each row, the shortest real walk of the bins." },
      { type: "bullet", text: "Anything in a plain shelf or workstation location falls back to a simple location-grouped list underneath the grid maps." },
      { type: "step", text: "Use “Spawn Remaining Builds” to create the individual Build records for the batch — each one auto-serialized and linked back to the batch." },
    ],
  },
  {
    heading: "4.8 RMAs (Returns)",
    intro: "RMAs track a returned unit from intake through teardown and resolution.",
    items: [
      { type: "step", text: "RMAs › + New RMA, linking the original Build/client and the reason for return." },
      { type: "step", text: "Add teardown lines for each component recovered, marking each as Scrap or Restock." },
      { type: "step", text: "“Process Teardown” returns any Restock lines to inventory automatically." },
      { type: "step", text: "Resolve the RMA once it's handled (e.g. Replaced, Refunded)." },
    ],
  },
]);

// ---------------------------------------------------------------------
// 5. Inventory & Purchasing
// ---------------------------------------------------------------------
const inventoryPurchasing = moduleSection(5, "Inventory & Purchasing", "Parts, the suppliers you buy them from, and the purchase orders that keep stock flowing.", [
  {
    heading: "5.1 Inventory (Parts)",
    items: [
      { type: "step", text: "Inventory › + New Part — set cost, margin (sell price is computed automatically), reorder threshold, and preferred supplier." },
      { type: "bullet", text: "A part's stock level, bin location, and full purchase/usage history live on its detail page." },
      { type: "bullet", text: "Parts at or below their reorder threshold are flagged on the Dashboard and feed the Auto-Procurement Queue (5.6)." },
    ],
  },
  {
    heading: "5.2 Suppliers & Supplier Reliability",
    items: [
      { type: "step", text: "Suppliers › + New Supplier with contact details, currency, and status." },
      { type: "bullet", text: "The Suppliers list shows a computed Reliability score based on actual delivery performance against expected dates." },
      { type: "step", text: "Record Blackout Periods on a supplier (e.g. factory holidays) so the Procurement Queue and lead-time estimates account for them." },
    ],
  },
  {
    heading: "5.3 Sourcing Prospects",
    items: [
      { type: "step", text: "Sourcing › + New Prospect to track a potential new supplier or part source before committing." },
      { type: "step", text: "Convert a prospect once it's vetted — promoting it into a real Supplier record." },
    ],
  },
  {
    heading: "5.4 Purchase Orders & Receiving",
    intro: "A PO tracks what you've ordered from a supplier and what's actually arrived, including partial receiving.",
    items: [
      { type: "step", text: "Purchase Orders › + New PO, choose the supplier, and add line items with quantity ordered and unit cost." },
      { type: "step", text: "Confirm the PO, then use Receive on each line as stock physically arrives — partial receipts are fully supported and the PO's status advances automatically (Confirmed → Partially Received → Received)." },
      { type: "bullet", text: "Each receive automatically files an itemized entry in the Expenses ledger (see 7.3) — that's what makes the BAS Generator's GST Paid figure real instead of an estimate." },
    ],
  },
  {
    heading: "5.5 Landed Cost Distribution",
    intro: "Freight and duty paid on a shipment don't sit as a separate line — they get spread across the parts that arrived in it, so each part's recorded cost reflects what it actually cost to get here.",
    items: [
      { type: "step", text: "On a received PO, enter the actual freight and duty paid plus the real received date (this also feeds Supplier Reliability)." },
      { type: "step", text: "Click Apply to distribute that cost across the received lines — each part's unit cost updates as a moving average, and the PO is marked as applied so it can't be double-counted." },
    ],
  },
  {
    heading: "5.6 Auto-Procurement Queue",
    intro: "A running scan of every part at or below its reorder threshold, grouped by preferred supplier.",
    items: [
      { type: "step", text: "Purchasing › Procurement Queue to see everything that needs reordering right now." },
      { type: "step", text: "“Create Draft PO” turns a supplier's flagged parts straight into a draft Purchase Order, ready to review and confirm." },
    ],
  },
]);

// ---------------------------------------------------------------------
// 6. Warehouse
// ---------------------------------------------------------------------
const warehouse = moduleSection(6, "Warehouse", "Where things physically live, and the equipment that lives alongside them.", [
  {
    heading: "6.1 Locations & Gridfinity Setup",
    intro: "A Location is any physical storage spot — Parts Storage, Finished Kit Storage, or a Workstation. A location can optionally be a specific cell in a printed Gridfinity baseplate, which is what powers the visual pick-list grid maps in Chapter 4.7.",
    items: [
      { type: "step", text: "Warehouse › Locations › Add Location." },
      { type: "step", text: "For a plain shelf or workstation, leave Baseplate Name/Grid X/Grid Y blank." },
      { type: "step", text: "For a Gridfinity bin, set a Baseplate Name (shared by every cell on that same physical baseplate, e.g. “Drawer 1”) and that cell's Grid X / Grid Y coordinate." },
      { type: "step", text: "Assign parts to their location from the part's own edit form." },
      { type: "note", text: "Coordinates are just a simple (column, row) pair starting at (0,0) in a baseplate's top-left cell — they don't need to match any particular Gridfinity part numbering, just be consistent with the physical layout." },
    ],
  },
  {
    heading: "6.2 Assets & Power Monitoring",
    intro: "Assets are your equipment — printers, tools, workstations — with purchase cost, location, and maintenance notes. An asset on a monitored smart plug can also report live power draw.",
    items: [
      { type: "step", text: "Warehouse › Assets › + New Asset." },
      { type: "step", text: "To enable power monitoring, set the asset's Power Plug Reference to that plug's LAN IP or hostname (e.g. 192.168.1.42)." },
      { type: "bullet", text: "Once the Local Agent (Chapter 11) is running and polling, the asset's detail page shows its latest wattage reading and a log of recent readings." },
    ],
  },
]);

// ---------------------------------------------------------------------
// 7. Insights & Financials
// ---------------------------------------------------------------------
const insights = moduleSection(7, "Insights & Financials", "Reporting and the financial tools that turn your records into numbers you can act on — and eventually hand to your bookkeeper.", [
  {
    heading: "7.1 Analytics",
    items: [
      { type: "bullet", text: "Insights › Analytics gives a rolled-up view of sales, production, and inventory trends across the business." },
    ],
  },
  {
    heading: "7.2 Reports",
    items: [
      { type: "bullet", text: "Insights › Reports offers downloadable CSVs — inventory valuation, sales order history, and outstanding invoices — ready to open in a spreadsheet or hand to your accountant." },
    ],
  },
  {
    heading: "7.3 Expenses Ledger",
    intro: "The real source for the BAS Generator's GST Paid figure. Purchase order receipts file themselves here automatically, itemized line by line; everything else you pay GST on — rent, software subscriptions, freight you pay directly, tools, utilities, professional services — you add manually.",
    items: [
      { type: "step", text: "Insights › Expenses to see the full ledger, filterable by category." },
      { type: "step", text: "Use Record Expense for anything that isn't a PO receipt — pick a category, enter the amount ex-GST, and GST defaults to 10% (override it if the real figure differs)." },
      { type: "note", text: "Keeping this ledger current is what makes the BAS Generator's GST Paid figure trustworthy — it can only be as complete as what's entered here." },
    ],
  },
  {
    heading: "7.4 BAS Generator",
    intro: "Produces a GST estimate for a date range: GST Collected (calculated exactly from sent/paid invoices) against GST Paid (summed from the Expenses ledger).",
    items: [
      { type: "step", text: "Insights › BAS Generator, choose a period start and end, and click Generate Estimate." },
      { type: "step", text: "Every past estimate is kept below for reference." },
      { type: "note", text: "This is a strong starting point for BAS preparation, not a lodging-ready figure on its own — always check with your bookkeeper or accountant before lodging." },
    ],
  },
  {
    heading: "7.5 CapEx Calculator",
    intro: "A quick break-even calculator for equipment purchases — how many months until a new machine pays for itself.",
    items: [
      { type: "step", text: "Insights › CapEx Calculator, enter the equipment cost and its projected monthly revenue and cost impact." },
      { type: "bullet", text: "Every saved scenario shows its computed break-even point side by side, so you can compare options." },
    ],
  },
]);

// ---------------------------------------------------------------------
// 8. Tools
// ---------------------------------------------------------------------
const tools = moduleSection(8, "Tools", "Shared utilities that support every other module.", [
  {
    heading: "8.1 Documents",
    items: [
      { type: "step", text: "Tools › Documents › Upload, choosing a document type and optionally linking it to a client, supplier, PO, sales order, kit, or build." },
      { type: "bullet", text: "Filter the list by document type to find what you need quickly." },
    ],
  },
  {
    heading: "8.2 Labels & Quick Links",
    items: [
      { type: "bullet", text: "Quick Links stores reusable URLs — review pages, help docs, landing pages — optionally tied to a specific part or kit." },
      { type: "bullet", text: "This module also generates QR codes for parts, kits, and links, and manages sticker/label templates for printing them." },
    ],
  },
]);

// ---------------------------------------------------------------------
// 9. Administration
// ---------------------------------------------------------------------
const admin = moduleSection(9, "Administration", "Company-wide configuration — usually a one-time setup per item, revisited only when something changes.", [
  {
    heading: "9.1 Overview",
    items: [{ type: "bullet", text: "A snapshot of key settings — numbering, reference lists, Shopify connection status, and user counts by role — with links into each area." }],
  },
  {
    heading: "9.2 Company",
    items: [
      { type: "bullet", text: "Core company details (name, ABN, address, logo), default currency/margin/GST rate, default payment terms, invoice reminder timing, and your labor rate per hour (used by Routing & Operations' true COGS calculation)." },
      { type: "bullet", text: "Reference lists — Part Categories, Kit Categories, Asset Types, Document Types, Payment Terms, Order Sources — are managed from this page too." },
      { type: "bullet", text: "Packing list field toggles and Email Templates (Quote Sent, Invoice Sent, Payment Reminder, Build Complete) also live here." },
    ],
  },
  {
    heading: "9.3 Duties & Shipping",
    items: [{ type: "bullet", text: "Destination countries, HS codes, customs agents, shipping carriers, and duty rates — what drives the international shipping/duty estimates shown on Quotes." }],
  },
  {
    heading: "9.4 Numbering",
    items: [{ type: "bullet", text: "Controls the prefix, next number, and zero-padding for every auto-generated number in the system — Parts, Suppliers, Kits, Sales Orders, Purchase Orders, Quotes, Invoices, Builds, Serials, and Batch Runs." }],
  },
  {
    heading: "9.5 Integrations",
    items: [
      { type: "bullet", text: "Connect and test the Shopify storefront sync from here." },
      { type: "bullet", text: "Stripe (for Invoice pay links) is configured at the deployment/environment level — see DEPLOYMENT.md — rather than through this page." },
    ],
  },
  {
    heading: "9.6 Security",
    items: [
      { type: "bullet", text: "Add, edit, and remove user accounts, and set each user's role (Owner or Workshop)." },
      { type: "bullet", text: "Change your own password from here after your first login." },
    ],
  },
  {
    heading: "9.7 Appearance",
    intro: "Every brand color, for both light and dark mode, is editable live — changes apply across the whole app immediately.",
    items: [
      { type: "bullet", text: "Adjust page background, card background, text colors, accent color, borders, and sidebar colors independently for light and dark mode." },
      { type: "bullet", text: "“Reset to Brand Defaults” restores Mint Motive's standard palette (Muted Teal accent, Charcoal text, Eggshell background, Carbon Black dark mode)." },
    ],
  },
  {
    heading: "9.8 Audit Log",
    intro: "A fully automatic, global record of every UPDATE and DELETE the app makes, on any table — not something that has to be turned on per screen.",
    items: [
      { type: "bullet", text: "Every change shows the table affected, the record, the action, who was signed in, and when." },
      { type: "bullet", text: "A small number of high-noise internal tables (the audit log itself, and background numbering counters) are excluded so the log stays readable." },
      { type: "bullet", text: "Filter by table to investigate a specific change." },
    ],
  },
  {
    heading: "9.9 Local Agent",
    intro: "Generates and displays the API key the Local Agent uses to report back to MintMotive Ops, plus setup instructions, a list of power-monitored assets, and recent firmware flash activity. See Chapter 11 for the full walkthrough.",
    items: [],
  },
]);

// ---------------------------------------------------------------------
// 10. Roles, Login & Everyday Tips (short, practical, non-redundant)
// ---------------------------------------------------------------------
const tips = [
  h1("10. Tips & Troubleshooting"),
  h2("10.1 General Tips"),
  bullet("Use the top-bar search first — it's usually faster than navigating into a module's list to find one record."),
  bullet("The Dashboard's low-stock and unpaid-invoice tiles are meant to be checked daily — they reflect your real records, not a cached report."),
  bullet("When in doubt about whether a number is exact or estimated (the BAS Generator, duty/freight estimates on Quotes), the page itself says so — look for the note directly under the figure."),
  bullet("Every module's list view supports filtering — by status, category, or a search box — near the top of the page."),
  h2("10.2 Common Questions"),
  pRich([new TextRun({ text: "“I deleted something by mistake — can I see what happened?” ", bold: true }), new TextRun({ text: "Check Administration › Audit Log, filtered to that table. It records every delete automatically." })]),
  pRich([new TextRun({ text: "“Why doesn't the invoice pay link work?” ", bold: true }), new TextRun({ text: "Stripe needs to be configured for your deployment — see DEPLOYMENT.md — before pay links can be generated." })]),
  pRich([new TextRun({ text: "“Why is my BAS GST Paid figure lower than expected?” ", bold: true }), new TextRun({ text: "It's summed from the Expenses ledger (7.3). If a business expense besides PO receipts hasn't been entered there yet, it won't show up in the BAS estimate — add it and regenerate." })]),
  pRich([new TextRun({ text: "“The Flash to Device button says it can't reach the Local Agent.” ", bold: true }), new TextRun({ text: "The Local Agent has to be running on the same PC you're using to flash — see Chapter 11." })]),
];

// ---------------------------------------------------------------------
// 11. Local Agent Setup (Firmware Flashing & IoT Power Monitoring)
// ---------------------------------------------------------------------
const localAgent = [
  h1("11. Local Agent Setup (Firmware Flashing & IoT Power Monitoring)"),
  p("A browser page can't talk to a USB-connected programmer, and it can't poll a smart plug on your workshop LAN directly — for good security reasons, browsers don't allow that. The Local Agent is a small helper program that runs on the workshop PC that has that hardware physically attached, and does that work on MintMotive Ops' behalf. It's how Firmware Flashing (Chapter 4.3) and IoT Power Monitoring (Chapter 6.2) are able to work from right inside the app, without needing a separate desktop application for day-to-day use."),
  p("It listens only on http://localhost:8765 on that one PC. A MintMotive Ops page open in a browser on that same machine can reach it — browsers specifically allow a page to call back to “localhost” even when the page itself is served from somewhere else — but nothing outside that machine can reach it."),

  h2("11.1 One-Time Setup"),
  step("In MintMotive Ops, go to Administration › Local Agent and click Generate Key. This creates the shared secret the Local Agent uses to authenticate back to the app — keep it private, the same as a password.", 0, "step-11-1"),
  step("On the workshop PC (the one with the USB programmer plugged in, or on the same network as your smart plugs), copy the local_agent folder from the MintMotive Ops package.", 0, "step-11-1"),
  step("Install Python 3.9 or later if it isn't already there.", 0, "step-11-1"),
  step("Install the Local Agent's dependencies: pip install -r local_agent/requirements.txt.", 0, "step-11-1"),
  step("For firmware flashing, install avrdude and make sure it's on your system PATH (or point avrdude_path at it in the next step) — on Windows it's easiest to install via an Arduino IDE setup, which bundles avrdude; on macOS, brew install avrdude; on Linux, your package manager's avrdude package.", 0, "step-11-1"),
  step("Copy local_agent/config.example.json to local_agent/config.json and fill in: mintmotive_url (the address you use to reach MintMotive Ops in your browser), api_key (the key from step 1), and the programmer/mcu/baud_rate values that match your board.", 0, "step-11-1"),
  step("Run it: python3 local_agent/flasher_agent.py. You should see “MintMotive Ops Local Agent listening on http://localhost:8765.” Leave this running while you're flashing boards or want power readings collected.", 0, "step-11-1"),

  h2("11.2 Flashing a Board"),
  step("On that same PC, open MintMotive Ops and go to a Build's detail page (or a Kit's Firmware Versions section for a bench unit not yet tied to a Build).", 0, "step-11-2"),
  step("Under “Flash to Device,” choose the firmware version you want to flash.", 0, "step-11-2"),
  step("Click “⚡ Flash to Device.” MintMotive Ops asks the Local Agent to download that firmware file, auto-detect the connected USB board, and run avrdude.", 0, "step-11-2"),
  step("The real result — success or failure, with the full avrdude output — is reported back automatically and appears in the Build's Flash History and in Administration › Local Agent.", 0, "step-11-2"),
  note("If you have more than one board or programmer plugged in at once, set port_override in config.json to the specific port you want the Local Agent to always use, instead of relying on auto-detection."),

  h2("11.3 Power Monitoring"),
  step("On an Asset's detail page (Warehouse › Assets), set its Power Plug Reference to that plug's LAN IP address or hostname (e.g. 192.168.1.42 or shelly-printer-1).", 0, "step-11-3"),
  step("As long as the Local Agent is running with mintmotive_url and api_key set, it polls every configured plug automatically (every 30 seconds by default) and reports wattage back.", 0, "step-11-3"),
  step("The asset's detail page then shows its latest reading and a short history.", 0, "step-11-3"),
  note("Shelly Gen1 and Tasmota-style smart plugs are supported out of the box. For a different brand, a developer can extend the _read_plug_watts() function in local_agent/flasher_agent.py — it just needs to return a wattage number for a given plug reference."),

  h2("11.4 Troubleshooting"),
  bullet("“Can't reach the Local Agent” in the browser — make sure flasher_agent.py is running, and that you're opening MintMotive Ops from the same PC the agent is running on."),
  bullet("“No USB serial device found” — check the board is plugged in, its drivers are installed, and no other program (like the Arduino IDE's Serial Monitor) has the port open."),
  bullet("avrdude errors — the raw avrdude output is included in the Flash History log line, so you can see exactly what it reported."),
  bullet("No power readings showing up — confirm mintmotive_url and api_key are set in config.json, and that the plug's address is reachable from the workshop PC."),
];

// ---------------------------------------------------------------------
// Assemble
// ---------------------------------------------------------------------
const doc = new Document({
  features: { updateFields: true },
  numbering: {
    config: [
      {
        reference: "bullet-list",
        levels: [
          { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 260 } } } },
          { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 820, hanging: 260 } } } },
        ],
      },
      // Each step-list reference collected while building the content above
      // gets its own independent counter, so every subsection's numbered
      // steps restart at 1 instead of counting up across the whole guide.
      ...Array.from(stepRefs).map((reference) => ({
        reference,
        levels: [
          { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 460, hanging: 260 } } } },
        ],
      })),
    ],
  },
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 22, color: CARBON } },
    },
    paragraphStyles: [
      {
        id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 32, bold: true, color: CARBON },
        paragraph: { spacing: { before: 400, after: 200 }, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: TEAL, space: 4 } } },
      },
      {
        id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 26, bold: true, color: CHARCOAL },
        paragraph: { spacing: { before: 320, after: 160 } },
      },
      {
        id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: "Calibri", size: 23, bold: true, color: CHARCOAL },
        paragraph: { spacing: { before: 240, after: 120 } },
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 },
          margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 },
        },
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              alignment: AlignmentType.CENTER,
              border: { top: { style: BorderStyle.SINGLE, size: 4, color: "CCCCCC", space: 6 } },
              children: [
                new TextRun({ text: "MintMotive Ops User Guide", size: 16, color: CHARCOAL }),
                new TextRun({ text: "   ·   ", size: 16, color: CHARCOAL }),
                new TextRun({ children: [PageNumber.CURRENT], size: 16, color: CHARCOAL }),
              ],
            }),
          ],
        }),
      },
      children: [
        ...cover,
        ...contents,
        ...gettingStarted,
        pageBreak(),
        ...dashboard,
        pageBreak(),
        ...salesPipeline,
        pageBreak(),
        ...production,
        pageBreak(),
        ...inventoryPurchasing,
        pageBreak(),
        ...warehouse,
        pageBreak(),
        ...insights,
        pageBreak(),
        ...tools,
        pageBreak(),
        ...admin,
        pageBreak(),
        ...localAgent,
        pageBreak(),
        ...tips,
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync("/root/mintmotive-ops/docs_build/MintMotive_Ops_User_Guide.docx", buffer);
  console.log("Written.");
});
