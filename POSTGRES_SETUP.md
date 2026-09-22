# Using PostgreSQL instead of SQLite

By default this app stores everything in a single SQLite file
(`instance/mintmotive.db`) — zero setup, and plenty for one server. The
main reason to switch to PostgreSQL is the situation you're in now: **two
servers (your Azure VM and your rented VPS) that should share one real
database**, instead of each keeping its own file that only you can keep in
sync by copying it around.

Nothing in the app's business logic changes — every screen, every report,
every calculation works exactly the same either way. Switching backends is
just: stand up a Postgres database somewhere, set one environment variable
(`DATABASE_URL`) pointing at it, and both servers point at the same one.

## 1. Get a Postgres database

Two reasonable options, given you already have an Azure VM:

**Option A — Azure Database for PostgreSQL (managed, recommended).** Azure
runs and backs up the Postgres server for you — you don't have to patch it,
back it up yourself, or worry about it going down with one of your two app
servers. In the Azure Portal: **Create a resource > Azure Database for
PostgreSQL > Flexible Server**. Pick the smallest/burstable tier — this
app's data volume is tiny. Note down, from the server's "Connect" page:
the server hostname, the admin username, and the password you set. Under
**Networking**, allow both your Azure VM's and your rented VPS's public IPs
(or, simpler while testing, temporarily allow "Allow public access from any
Azure service" plus your VPS's specific IP).

**Option B — Run Postgres yourself** on the Azure VM (or the VPS) instead
of paying for a managed instance. Download the Windows installer from
https://www.postgresql.org/download/windows/, run it (remember the
password you set for the `postgres` superuser), and it installs as a
Windows service automatically — it'll already be running and set to start
on boot. This means that server becomes a dependency for the other one
though: if the machine hosting Postgres is down, the app on both machines
stops working, not just the one hosting it. Option A avoids that coupling.

Either way, create a database and dedicated user for the app rather than
using the default `postgres` database/user (using pgAdmin, the tool that
comes with the Windows installer, or Azure's portal query editor):

```sql
CREATE DATABASE mintmotive;
CREATE USER mintmotive_app WITH PASSWORD 'choose-a-strong-password';
GRANT ALL PRIVILEGES ON DATABASE mintmotive TO mintmotive_app;
```

## 2. Build your connection string

```
postgresql://mintmotive_app:choose-a-strong-password@your-server-host:5432/mintmotive
```

For Azure Database for PostgreSQL, the hostname is the "Server name" from
its Overview page (something like `your-server.postgres.database.azure.com`),
and it needs SSL — append `?sslmode=require`:

```
postgresql://mintmotive_app:choose-a-strong-password@your-server.postgres.database.azure.com:5432/mintmotive?sslmode=require
```

## 3. Point the app at it

Set `DATABASE_URL` to that connection string as a permanent (not just
current-session) environment variable on **both** servers, so the Task
Scheduler-launched app picks it up too, not just a manual PowerShell test:

```powershell
setx DATABASE_URL "postgresql://mintmotive_app:...@...:5432/mintmotive?sslmode=require" /M
```

The `/M` sets it machine-wide (needs an Administrator PowerShell). This
only takes effect for *new* processes started after you run it — close and
reopen PowerShell, and if the "MintMotive Ops" Task Scheduler task is
already running, stop and start it again (right-click → End, then → Run)
so it picks up the new variable.

Once `DATABASE_URL` is set, `pip install -r requirements.txt` (which now
includes `psycopg2-binary`, the Postgres driver) and running the app
exactly as before — `python serve.py` — automatically uses Postgres
instead of SQLite. No other config, no code changes.

## 4. Get your data in

**Starting fresh, no existing data worth keeping:** just run the normal
first-time setup against the new database:

```powershell
python seed.py reece@mintmotive.com.au "Reece"
```

**Already have real data in `instance/mintmotive.db`** (suppliers, parts,
orders, etc. from testing or from running one server for a while) and want
to bring it across instead of starting over:

```powershell
python migrate_sqlite_to_postgres.py
```

Run this once, from the server that currently has the SQLite file you want
to keep. It copies every row across table-by-table and fixes up Postgres's
internal auto-numbering afterward, and refuses to run if the target
database already has data in it (so it can't be run twice by accident and
double up everything).

## 5. Set up the second server

On the other server, set the exact same `DATABASE_URL` (step 3), install
requirements, and start the app the same way — it's now reading and
writing the same database as the first one. Remember from
`WINDOWS_SERVER_DEPLOYMENT.md`: even with a shared Postgres database
removing the single-writer limitation SQLite had, only run the app live on
one server's public HTTPS address at a time (one subdomain pointed at one
IP) unless you specifically want to build out a load-balanced setup later
— the shared database means the *other* server is now a genuinely ready
hot-standby (flip DNS to it and it has every up-to-the-second record),
which is a real improvement over the SQLite copy-the-file approach, even
without running both live simultaneously.

## Rolling back

If anything about Postgres doesn't work out, deleting/un-setting
`DATABASE_URL` (`setx DATABASE_URL "" /M`, then remove it fully from
System Properties > Environment Variables) makes the app fall straight
back to its original SQLite file — nothing about the SQLite path was
removed, it's still the default whenever `DATABASE_URL` isn't set.
