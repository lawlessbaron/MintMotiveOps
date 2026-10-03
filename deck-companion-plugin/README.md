# Deck Companion

An AI game companion + **Memory Lane** journal for the Steam Deck, built as a
[Decky Loader](https://decky.xyz) plugin.

It lives in the Quick Access Menu (the `...` button) and does three things:

- **Ask your companion** — mid-game, ask for a hint, a reminder, or "what's that boss's weakness?"
  Keep **No spoilers** on and it gives nudges without revealing what's ahead.
- **Catch me up** — returning to a game after a break? It reads your saved notes and
  writes a friendly "previously on…" recap.
- **Memory Lane** — save a session note any time. Over weeks and months this becomes a
  timeline of your gaming life.

It only ever works with **your own games and your own notes** — it never downloads,
hosts, or links game files.

---

## How it's built

| Part | File | What it does |
|------|------|--------------|
| Frontend (React) | `src/index.tsx` | The panel UI; calls the backend over Decky's bridge |
| Backend (Python) | `main.py` | Holds your API key, calls the Claude API, stores your journal |
| Manifest | `plugin.json` | Tells Decky about the plugin |
| Build | `package.json`, `rollup.config.js`, `tsconfig.json` | Bundles the frontend into `dist/` |

Your API key and journal are stored privately on the Deck in Decky's plugin
settings directory — nothing is sent anywhere except your own request to the Claude API.

---

## Build it (on your computer)

You need [Node.js](https://nodejs.org) 18+ and [pnpm](https://pnpm.io)
(`npm install -g pnpm`).

```bash
cd deck-companion-plugin
pnpm install
pnpm run build
```

That produces `dist/index.js`. The folder is now a complete, installable plugin.

> Type-checking and building work on any computer — you don't need the Deck to develop.

---

## Install it (on the Steam Deck)

1. Install [Decky Loader](https://decky.xyz) on your Deck (one-time, follow their guide).
2. Copy this whole `deck-companion-plugin` folder into the Deck's plugin directory:
   `~/homebrew/plugins/deck-companion-plugin`
   (easiest over the network with `scp -r deck-companion-plugin deck@<deck-ip>:~/homebrew/plugins/`,
   or on a USB drive in Desktop Mode).
3. In Gaming Mode, open the Quick Access Menu → the Decky (plug) icon → you'll see **Deck Companion**.

### First run

1. Open **Deck Companion** → **Settings**.
2. Paste your Anthropic API key (get one at <https://console.anthropic.com>) and tap **Save settings**.
3. (Optional) Change the model. `claude-opus-5-5` is the sharpest; `claude-haiku-4-5` is the cheapest.
4. Launch a game, open the panel, and ask away.

---

## Developing

- `pnpm run watch` rebuilds `dist/` whenever you edit `src/`.
- Backend methods live on the `Plugin` class in `main.py`; each one is wired to the
  frontend by name via `callable("method_name")` in `src/index.tsx`.
- Decky logs backend output — handy for debugging the Python side.

## Ideas for later

- Auto-save a session note when you close a game (detect the app closing).
- Let the companion read your recent screenshots to jog your memory.
- A full-screen Memory Lane timeline with cover art.
- Per-game "cheat sheet" you can pin.

## A note on the Claude call

`main.py` calls the Claude API with Python's standard-library `urllib` so there's
nothing to pip-install on the Deck. If you'd rather use the official `anthropic`
SDK, vendor it into the plugin and swap out the `_call_claude` helper.
