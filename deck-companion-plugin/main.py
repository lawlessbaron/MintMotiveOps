"""
Deck Companion - Python backend.

This runs on the Steam Deck itself. The React frontend (src/index.tsx) calls
these methods over Decky's bridge. This half does the things the frontend can't
safely do: hold your API key, call the Claude API, and read/write your journal
on disk.

Note on the Claude call: we use Python's standard-library `urllib` instead of the
official `anthropic` SDK. Decky plugins run in a constrained Python environment
where pip-installing extra packages on the Deck is fiddly, and `urllib` ships with
Python so there's nothing to install. If you'd rather use the official SDK, you
can vendor it into the plugin and swap `_call_claude` for `anthropic.Anthropic(...)`.
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone

import decky  # provided by Decky Loader at runtime

# --- Where we keep things -------------------------------------------------
# Decky gives every plugin a private settings directory that survives reboots.
SETTINGS_DIR = decky.DECKY_PLUGIN_SETTINGS_DIR
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")
JOURNAL_PATH = os.path.join(SETTINGS_DIR, "journal.json")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
# Default to the most capable model. You can switch to a cheaper/faster one in
# Settings: "claude-sonnet-5-5" or "claude-haiku-4-5".
DEFAULT_MODEL = "claude-opus-5-5"


# --- Tiny JSON file helpers ----------------------------------------------
def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# --- The actual Claude call ----------------------------------------------
def _call_claude(api_key, model, system, user_text, max_tokens=1024):
    """Send one message to Claude and return the plain-text reply."""
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_text}],
    }).encode("utf-8")

    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=body,
        method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    # The reply is a list of content blocks; we want the text ones.
    parts = [b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()


class Plugin:
    # --- Lifecycle (Decky calls these automatically) ---------------------
    async def _main(self):
        decky.logger.info("Deck Companion loaded.")

    async def _unload(self):
        decky.logger.info("Deck Companion unloaded.")

    # --- Settings --------------------------------------------------------
    async def get_settings(self):
        """Frontend asks this on open. We never send the key back, just whether one is set."""
        s = _read_json(SETTINGS_PATH, {})
        return {
            "has_key": bool(s.get("api_key")),
            "model": s.get("model", DEFAULT_MODEL),
        }

    async def save_settings(self, api_key, model):
        s = _read_json(SETTINGS_PATH, {})
        # Only overwrite the key if the user actually typed a new one.
        if api_key:
            s["api_key"] = api_key.strip()
        s["model"] = (model or DEFAULT_MODEL).strip()
        _write_json(SETTINGS_PATH, s)
        return {"ok": True}

    def _creds(self):
        s = _read_json(SETTINGS_PATH, {})
        return s.get("api_key"), s.get("model", DEFAULT_MODEL)

    # --- Companion: ask a question about the game you're playing ---------
    async def ask_companion(self, game, question, no_spoilers):
        api_key, model = self._creds()
        if not api_key:
            return {"ok": False, "error": "No API key set yet. Add one in Settings below."}

        spoiler_rule = (
            "The player does NOT want story spoilers beyond where they currently are. "
            "Give hints and gentle nudges; never reveal future plot points, boss outcomes, or endings."
            if no_spoilers else
            "You may reference later content if it genuinely helps, but keep it brief."
        )
        system = (
            "You are a friendly in-game companion for a Steam Deck player. "
            f"They are currently playing: {game}. "
            f"{spoiler_rule} "
            "Be concise, warm, and practical - answer in a few sentences, not an essay."
        )
        try:
            text = _call_claude(api_key, model, system, question)
            return {"ok": True, "text": text}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            return {"ok": False, "error": f"API error {e.code}: {detail[:300]}"}
        except Exception as e:  # noqa: BLE001 - surface anything to the UI
            return {"ok": False, "error": str(e)}

    # --- Memory Lane: catch me up on where I left off -------------------
    async def catch_me_up(self, game):
        api_key, model = self._creds()
        if not api_key:
            return {"ok": False, "error": "No API key set yet. Add one in Settings below."}

        journal = _read_json(JOURNAL_PATH, [])
        notes = [e for e in journal if e.get("game") == game]
        if not notes:
            return {
                "ok": True,
                "text": f"No saved notes for {game} yet. Save a session note and I'll remember it for next time!",
            }

        joined = "\n".join(f"- ({e.get('date', '')[:10]}) {e.get('text', '')}" for e in notes)
        system = (
            "You help a returning player remember where they left off. "
            "Given their past session notes, write a short, friendly 'previously on...' recap. "
            "Do not invent events that aren't in the notes."
        )
        user_text = f"Game: {game}\nMy past notes:\n{joined}\n\nCatch me up on what I was doing."
        try:
            text = _call_claude(api_key, model, system, user_text, max_tokens=800)
            return {"ok": True, "text": text}
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "ignore")
            return {"ok": False, "error": f"API error {e.code}: {detail[:300]}"}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    # --- Journal storage (the Memory Lane timeline) --------------------
    async def add_journal_entry(self, game, text, kind="note"):
        if not text or not text.strip():
            return {"ok": False, "error": "Nothing to save."}
        journal = _read_json(JOURNAL_PATH, [])
        journal.append({
            "game": game or "Unknown",
            "text": text.strip(),
            "kind": kind,
            "date": datetime.now(timezone.utc).isoformat(),
        })
        _write_json(JOURNAL_PATH, journal)
        return {"ok": True, "count": len(journal)}

    async def get_journal(self, game=None, limit=20):
        journal = _read_json(JOURNAL_PATH, [])
        if game:
            journal = [e for e in journal if e.get("game") == game]
        journal = sorted(journal, key=lambda e: e.get("date", ""), reverse=True)
        return {"ok": True, "entries": journal[:limit]}
