// Deck Companion - frontend (the panel in the Quick Access Menu).
//
// This is React. It draws the UI and calls the Python backend (main.py) through
// Decky's `callable` bridge. Each `callable(...)` below lines up with a method on
// the `Plugin` class in main.py, by name and by argument order.

import {
  definePlugin,
  staticClasses,
  PanelSection,
  PanelSectionRow,
  ButtonItem,
  TextField,
  ToggleField,
  Router,
} from "@decky/ui";
import { callable } from "@decky/api";
import { useEffect, useState } from "react";
import { FaGamepad } from "react-icons/fa";

// --- Bridge to the Python backend ---------------------------------------
// callable<[args...], ReturnType>("python_method_name")
const getSettings = callable<[], { has_key: boolean; model: string }>("get_settings");
const saveSettings = callable<[string, string], { ok: boolean }>("save_settings");
const askCompanion = callable<
  [string, string, boolean],
  { ok: boolean; text?: string; error?: string }
>("ask_companion");
const catchMeUp = callable<[string], { ok: boolean; text?: string; error?: string }>("catch_me_up");
const addJournalEntry = callable<[string, string, string], { ok: boolean; count?: number }>(
  "add_journal_entry"
);
const getJournal = callable<
  [string | null, number],
  { ok: boolean; entries: JournalEntry[] }
>("get_journal");

interface JournalEntry {
  game: string;
  text: string;
  kind: string;
  date: string;
}

// Ask Steam what game is running right now, so the companion has context.
function getCurrentGame(): string {
  try {
    // Router.MainRunningApp is provided by Steam; guard it in case it's undefined.
    const app = (Router as any)?.MainRunningApp;
    return app?.display_name || "your current game";
  } catch {
    return "your current game";
  }
}

function Content() {
  const [game, setGame] = useState<string>("your current game");

  // Companion
  const [question, setQuestion] = useState<string>("");
  const [answer, setAnswer] = useState<string>("");
  const [noSpoilers, setNoSpoilers] = useState<boolean>(true);

  // Memory Lane
  const [recap, setRecap] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const [entries, setEntries] = useState<JournalEntry[]>([]);

  // Settings
  const [apiKey, setApiKey] = useState<string>("");
  const [model, setModel] = useState<string>("claude-opus-5-5");
  const [hasKey, setHasKey] = useState<boolean>(false);

  const [busy, setBusy] = useState<boolean>(false);
  const [status, setStatus] = useState<string>("");

  // Load settings + current game when the panel opens.
  useEffect(() => {
    setGame(getCurrentGame());
    getSettings().then((s) => {
      setHasKey(s.has_key);
      setModel(s.model || "claude-opus-5-5");
    });
    refreshJournal();
  }, []);

  const refreshJournal = async () => {
    const res = await getJournal(null, 20);
    if (res.ok) setEntries(res.entries);
  };

  const onAsk = async () => {
    if (!question.trim()) return;
    setBusy(true);
    setAnswer("Thinking...");
    const res = await askCompanion(game, question, noSpoilers);
    setAnswer(res.ok ? res.text || "" : `⚠️ ${res.error}`);
    setBusy(false);
  };

  const onCatchUp = async () => {
    setBusy(true);
    setRecap("Remembering...");
    const res = await catchMeUp(game);
    setRecap(res.ok ? res.text || "" : `⚠️ ${res.error}`);
    setBusy(false);
  };

  const onSaveNote = async () => {
    if (!note.trim()) return;
    setBusy(true);
    const res = await addJournalEntry(game, note, "note");
    if (res.ok) {
      setNote("");
      setStatus("Saved to Memory Lane ✓");
      await refreshJournal();
    }
    setBusy(false);
  };

  const onSaveSettings = async () => {
    setBusy(true);
    await saveSettings(apiKey, model);
    setApiKey(""); // clear the field so the key isn't left on screen
    const s = await getSettings();
    setHasKey(s.has_key);
    setStatus("Settings saved ✓");
    setBusy(false);
  };

  return (
    <>
      {/* ---------------- Companion ---------------- */}
      <PanelSection title="Companion">
        <PanelSectionRow>
          <div style={{ fontSize: "0.8em", opacity: 0.8 }}>Playing: {game}</div>
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField
            label="Ask your companion"
            value={question}
            onChange={(e) => setQuestion(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ToggleField
            label="No spoilers"
            description="Hints only, nothing from ahead of where you are"
            checked={noSpoilers}
            onChange={setNoSpoilers}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onAsk} disabled={busy}>
            Ask
          </ButtonItem>
        </PanelSectionRow>
        {answer && (
          <PanelSectionRow>
            <div style={{ whiteSpace: "pre-wrap", fontSize: "0.85em" }}>{answer}</div>
          </PanelSectionRow>
        )}
      </PanelSection>

      {/* ---------------- Memory Lane ---------------- */}
      <PanelSection title="Memory Lane">
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onCatchUp} disabled={busy}>
            Catch me up
          </ButtonItem>
        </PanelSectionRow>
        {recap && (
          <PanelSectionRow>
            <div style={{ whiteSpace: "pre-wrap", fontSize: "0.85em" }}>{recap}</div>
          </PanelSectionRow>
        )}
        <PanelSectionRow>
          <TextField
            label="Save a session note"
            value={note}
            onChange={(e) => setNote(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onSaveNote} disabled={busy}>
            Save note
          </ButtonItem>
        </PanelSectionRow>
        {entries.length > 0 && (
          <PanelSectionRow>
            <div style={{ fontSize: "0.8em" }}>
              {entries.map((e, i) => (
                <div key={i} style={{ marginBottom: "6px", opacity: 0.9 }}>
                  <strong>{e.game}</strong>{" "}
                  <span style={{ opacity: 0.6 }}>{e.date.slice(0, 10)}</span>
                  <div>{e.text}</div>
                </div>
              ))}
            </div>
          </PanelSectionRow>
        )}
      </PanelSection>

      {/* ---------------- Settings ---------------- */}
      <PanelSection title="Settings">
        <PanelSectionRow>
          <div style={{ fontSize: "0.8em", opacity: 0.8 }}>
            API key: {hasKey ? "set ✓" : "not set"}
          </div>
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField
            label="Anthropic API key"
            value={apiKey}
            onChange={(e) => setApiKey(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <TextField
            label="Model"
            description="claude-opus-5-5 (best) · claude-sonnet-5-5 · claude-haiku-4-5 (cheapest)"
            value={model}
            onChange={(e) => setModel(e?.target?.value ?? "")}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem layout="below" onClick={onSaveSettings} disabled={busy}>
            Save settings
          </ButtonItem>
        </PanelSectionRow>
        {status && (
          <PanelSectionRow>
            <div style={{ fontSize: "0.8em", opacity: 0.8 }}>{status}</div>
          </PanelSectionRow>
        )}
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "Deck Companion",
  titleView: <div className={staticClasses.Title}>Deck Companion</div>,
  content: <Content />,
  icon: <FaGamepad />,
  onDismount() {
    // Nothing to clean up for now.
  },
}));
