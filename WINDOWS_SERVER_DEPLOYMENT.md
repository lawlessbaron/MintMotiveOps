# Deploying to a Windows Server (Azure VM / rented VPS)

This covers putting MintMotive Ops on a real Windows server so it's reachable
from the internet 24/7 — not just running on your own PC. It applies equally
to your Azure VM and your rented Windows VPS/RDP box; the steps are the same
either way, since both are just "a Windows machine with a public IP."

**Read this first — the one rule that matters most:**

By default this app stores everything in a single SQLite file
(`instance\mintmotive.db`). SQLite is great for a business this size, but
only one running copy of the app should ever be writing to a given database
file at a time. Since you now have two servers, treat them as **primary and
cold standby**, not as two servers running live at once:

- Pick one (say, the Azure VM) as the one you actually use day-to-day.
- The other one stays turned off, or running with no one pointed at it.
- Periodically copy `instance\mintmotive.db` from the primary to the standby
  (Section 7 below has a one-line way to do this). If the primary ever dies,
  you copy the latest `.db` file onto the standby, start it there, and
  point your DNS at it instead.

Running both live against their own independent copies of the database at
the same time will NOT give you redundancy — it'll just quietly create two
different versions of your data that don't agree with each other, and
there's no automatic way to merge them back. So: one live server at a time.

**If you'd rather avoid this file-copying dance entirely**, the app also
supports PostgreSQL — a real client-server database both machines can point
at over the network, so there's one source of truth instead of copied
files. See `POSTGRES_SETUP.md`. It's not required — SQLite is completely
fine to start with — but it's a straightforward switch (one environment
variable) whenever the file-copying starts feeling like a chore.

Everything below assumes you're doing this on whichever server you've
picked as primary. Repeat the same steps on the standby later if you want it
ready to go.

---

## 1. Connect to the server

- **Azure VM**: Azure Portal → your VM → "Connect" → RDP → download the
  `.rdp` file → open it → sign in with the admin username/password you set
  when creating the VM.
- **Rented VPS**: use whatever RDP details the provider emailed you — usually
  an IP address, username (often `Administrator`), and password. Windows
  has Remote Desktop Connection built in (Start menu → search "Remote
  Desktop Connection").

Once connected, you're looking at a desktop exactly like a normal Windows
PC — everything from here on is typed directly into that remote session.

## 2. Install Python and Git on the server

Same as your own PC — follow `WINDOWS_SETUP.md` sections 1 and 2 inside this
RDP session:

1. Download Python from https://www.python.org/downloads/ and run it,
   **ticking "Add python.exe to PATH"** on the first screen.
2. Download Git from https://git-scm.com/download/win and run it with the
   defaults.
3. Open PowerShell on the server and confirm both:
   ```
   python --version
   git --version
   ```

Servers don't have OneDrive syncing a folder by default, so the venv issue
you hit on your own PC shouldn't come up here — just make sure whatever
folder you use isn't inside a synced folder if this server ever gets
OneDrive or Google Drive installed on it later.

## 3. Get the code onto the server

Easiest path: copy `mintmotive-ops.zip` onto the server. Two ways to do
that over RDP:

- **Copy/paste**: On your own PC, copy the zip file (Ctrl+C). Click into the
  RDP window, paste (Ctrl+V) onto the server's desktop. Windows RDP shares
  the clipboard between the two machines by default.
- **Download directly on the server**: open a browser inside the RDP
  session and download it from wherever you're storing it (email
  attachment, cloud storage link, etc.).

Then, in a PowerShell window on the server:

```powershell
mkdir C:\MintMotiveOps
# move/extract the zip into it, e.g. right-click → Extract All → C:\MintMotiveOps
cd C:\MintMotiveOps\mintmotive-ops
```

Using `C:\MintMotiveOps` (not a OneDrive-synced path, not tucked inside
`Documents`) keeps things simple and matches the Task Scheduler paths below.

## 4. Set up the virtual environment and install dependencies

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

Because `requirements.txt` now has a Windows-specific line, this will
install **Waitress** here (instead of gunicorn, which doesn't run on
Windows at all).

## 5. Create your login and seed data

```powershell
python seed.py reece@mintmotive.com.au "Reece"
```

Copy the printed password — you'll need it to log in the first time.

## 6. Test it manually first

```powershell
python serve.py
```

You should see `MintMotive Ops serving on http://0.0.0.0:8000 (Waitress, 4 threads)`.
On the server itself, open a browser to `http://127.0.0.1:8000` and confirm
it loads and you can log in. Then `Ctrl+C` to stop it — this was just a
test. The next section makes it run permanently, in the background,
even after you disconnect your RDP session or the server reboots.

## 7. Run it permanently with Task Scheduler

RDP sessions and the programs in them normally stop when you disconnect.
Task Scheduler keeps the app running regardless.

1. Open **Task Scheduler** (Start menu → search for it).
2. **Action → Create Task…** (not "Create Basic Task" — the full dialog
   gives you the option you need below).
3. **General tab**:
   - Name: `MintMotive Ops`
   - Select **"Run whether user is logged on or not"**
   - Tick **"Run with highest privileges"**
4. **Triggers tab → New…**:
   - Begin the task: **At startup**
   - (Leave everything else default) → OK
5. **Actions tab → New…**:
   - Action: **Start a program**
   - Program/script: `C:\MintMotiveOps\mintmotive-ops\venv\Scripts\python.exe`
   - Add arguments: `serve.py`
   - Start in: `C:\MintMotiveOps\mintmotive-ops`
   - OK
6. **Conditions tab**: untick "Start the task only if the computer is on AC
   power" (irrelevant for a server, but VPS defaults sometimes have it on).
7. OK, then enter the server's admin password when prompted (required for
   "run whether logged on or not").

To start it right now without rebooting: find "MintMotive Ops" in the Task
Scheduler Library list, right-click → **Run**. To stop it: right-click →
**End**. To confirm it's alive: open `http://127.0.0.1:8000` in a browser
on the server.

From now on, the app starts automatically every time the server boots —
including after Windows Updates restart it — with no one needing to be
logged in.

> **Optional, more robust alternative:** tools like [NSSM](https://nssm.cc/)
> wrap the app as a real Windows Service, which adds automatic restart if
> the app itself crashes (Task Scheduler's "At startup" trigger won't
> restart it if `serve.py` dies mid-run, only on reboot). Task Scheduler is
> enough to start with; revisit NSSM later if you notice it going down
> unexpectedly.

**Keeping the standby server in sync**: whenever you want to refresh the
cold-standby copy, copy `instance\mintmotive.db` from the primary server to
the same path on the standby (drag-and-drop over RDP clipboard works for
this too, or a scheduled copy to shared storage if you want it automatic
later). Do this after big batches of work, or nightly — however current you
need the backup to be.

## 8. Open the firewall for the app

Two firewalls sit between the internet and the app: the cloud provider's
network firewall, and Windows' own firewall on the server.

- **Azure VM**: Portal → your VM → **Networking** → add an inbound port
  rule for **80** and **443** (source: Any, for a public site). Leave 8000
  closed to the internet — only Caddy (next section) needs to reach it, and
  it runs on the same machine.
- **Rented VPS**: check the provider's control panel for an equivalent
  firewall/security-group setting and open 80 and 443 there too.
- **Windows Firewall** on the server itself: it usually prompts you the
  first time a program tries to listen, similar to your own PC — choose
  Allow. If not, add inbound rules for 80/443 via **Windows Defender
  Firewall with Advanced Security → Inbound Rules → New Rule → Port**.

## 9. Put it behind HTTPS with a subdomain

Stripe's pay-now links and webhooks need a real HTTPS URL — `http://` alone
won't work, and Stripe requires it for anything beyond local testing.

Since `mintmotive.com.au` is already live as your Shopify storefront, the
safest approach is a **dedicated subdomain** just for this app —
`ops.mintmotive.com.au` — rather than touching the root domain's DNS or
switching nameservers (which risks the storefront). A subdomain only needs
one new DNS record; it doesn't affect anything else on the domain.

1. In whatever DNS provider manages `mintmotive.com.au` (wherever Shopify's
   domain is configured, or your registrar), add:
   - Type: **A**
   - Name: **ops**
   - Value: the server's public IP address (Azure Portal shows this as the
     VM's "Public IP address"; your VPS provider's panel shows the same for
     the rented box)
   - This only creates `ops.mintmotive.com.au` — it does not touch the `@`
     or `www` records your Shopify store uses.
2. Install **Caddy** on the server — a single executable that acts as a
   reverse proxy and gets you free, automatic HTTPS with no manual
   certificate wrangling:
   - Download the Windows binary from https://caddyserver.com/download
     (choose the plain `amd64` build) and save it as
     `C:\MintMotiveOps\caddy.exe`.
3. Create `C:\MintMotiveOps\Caddyfile` (plain text file, no extension) with:
   ```
   ops.mintmotive.com.au {
       reverse_proxy 127.0.0.1:8000
   }
   ```
4. Run it once to test:
   ```powershell
   cd C:\MintMotiveOps
   .\caddy.exe run
   ```
   Caddy will automatically get a Let's Encrypt certificate for
   `ops.mintmotive.com.au` the first time it starts (this needs DNS from
   step 1 to have already propagated — can take a few minutes to an hour).
   Once it's running, `https://ops.mintmotive.com.au` should load the app
   with a valid padlock.
5. Make Caddy permanent the same way as the app itself — another Task
   Scheduler entry:
   - Program/script: `C:\MintMotiveOps\caddy.exe`
   - Add arguments: `run`
   - Start in: `C:\MintMotiveOps`
   - Same "At startup" / "run whether logged on or not" settings as before.

Now `https://ops.mintmotive.com.au` is your permanent app URL, and your
Shopify storefront's DNS is completely untouched.

## 10. Point Stripe at the new URL

In your Stripe dashboard, update the webhook endpoint to
`https://ops.mintmotive.com.au/stripe/webhook` (see `DEPLOYMENT.md` for
where that's configured in Administration > Integrations). Test with a
real quote/invoice pay link once this is live to confirm the full loop —
email link → Stripe Checkout → webhook → invoice marked paid — works
end-to-end from outside your network.

## 11. Day-to-day from here

- The app just runs — no one needs to stay logged into RDP.
- To deploy an update: RDP in, stop the "MintMotive Ops" scheduled task,
  replace the code (keep `instance\mintmotive.db` untouched), `pip install
  -r requirements.txt` again if dependencies changed, start the task again.
- Back up `instance\mintmotive.db` regularly regardless of the standby
  server — copy it out to another location (cloud storage, your own PC)
  on whatever schedule matches how much data loss you could tolerate.
