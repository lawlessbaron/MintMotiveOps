# Running MintMotive Ops on Windows

This walks through getting the app running on your own Windows machine from scratch — Python, Git, and the app itself. About 15 minutes the first time.

## 1. Install Python

1. Go to https://www.python.org/downloads/ and download the latest Python 3 installer (3.11 or newer).
2. Run it. On the **very first screen**, tick **"Add python.exe to PATH"** at the bottom before clicking Install — this is the step people miss, and without it Windows won't find the `python` command.
3. When it finishes, open **PowerShell** (Start menu → type "PowerShell" → Enter) and check it worked:
   ```
   python --version
   ```
   You should see something like `Python 3.12.4`. If you get "not recognized", close and reopen PowerShell (PATH changes need a fresh window); if it still fails, re-run the installer and make sure that checkbox was ticked.

## 2. Install Git

1. Go to https://git-scm.com/download/win and download the installer.
2. Run it — the default options are fine for everything, just keep clicking Next.
3. Verify in PowerShell:
   ```
   git --version
   ```

## 3. Get the project onto your machine

You already have `mintmotive-ops.zip` from our chat. Pick a normal folder for it — e.g. `Documents\MintMotiveOps` — then:

1. Right-click the zip → **Extract All…** → choose that folder.
2. Open PowerShell and move into it:
   ```
   cd "$env:USERPROFILE\Documents\MintMotiveOps\mintmotive-ops"
   ```
   (adjust the path if you put it somewhere else)
3. Turn it into a Git repo, so you have version history from day one and can push it to GitHub later when you're ready to deploy (see `DEPLOYMENT.md`):
   ```
   git init
   git add .
   git commit -m "Initial commit"
   ```

## 4. Set up Python's virtual environment and install dependencies

A virtual environment keeps this app's packages separate from anything else on your machine — always use one.

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

You'll know the virtual environment is active because your prompt will start with `(venv)`. You need to run `venv\Scripts\activate` again every time you open a new PowerShell window to work on this — it doesn't stay on permanently.

> If PowerShell refuses to run `activate` with a message about execution policies, run this once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, then try again.

## 5. Create your login and starter data

Still inside the `(venv)` prompt:

```
python seed.py reece@mintmotive.com.au "Reece"
```

This prints a temporary password once — copy it before it scrolls away. If you've already got a database in `instance\mintmotive.db` from testing this in our chat, this step will just say your account already exists rather than overwriting it — that's expected and fine.

## 6. Run it

```
python run.py
```

Leave this window open (it's the server) and open a browser to **http://127.0.0.1:5000**. Log in with the email and password from step 5.

Windows may pop up a Firewall prompt the first time — choose **Allow access** (Private networks is enough; you don't need Public).

To stop the server later, click into that PowerShell window and press `Ctrl+C`.

## Day-to-day after this

Every time you come back to work on it:

```
cd "$env:USERPROFILE\Documents\MintMotiveOps\mintmotive-ops"
venv\Scripts\activate
python run.py
```

## If something goes wrong

- **`python` or `pip` not recognized** — Python wasn't added to PATH in step 1. Easiest fix: uninstall Python from "Add or remove programs", reinstall, and tick the PATH checkbox this time.
- **`pip install` fails on a package** — run `python -m pip install --upgrade pip` first, then retry `pip install -r requirements.txt`.
- **Port 5000 already in use** — something else on your machine is using it (sometimes an Apple/Bonjour service does). Run `$env:PORT=5001; python run.py` instead, and open http://127.0.0.1:5001.
- **You want a GUI for Git instead of the command line** — GitHub Desktop (https://desktop.github.com) works fine on top of the same repo; `git init`/`add`/`commit` above are the only commands you strictly need at the terminal.
