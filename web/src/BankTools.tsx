import { useEffect, useState } from "react";
import type { Box, Pokemon } from "./types";
export interface Trainer {
  ot: string;
  tid: number;
  sid: number;
  language: number;
  gender: number;
}
interface Backup {
  id: string;
  time: number;
  action: string;
  current: boolean;
  valid?: boolean;
}
interface Event {
  id: string;
  time: number;
  action: string;
}
export async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { "X-PkMn-SBank": "1", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : "Check the entered values and try again.",
    );
  return data;
}
export function ImportTools({
  ready,
  onChange,
}: {
  ready: boolean;
  onChange: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [result, setResult] = useState<{
    name: string;
    save: string;
    pokemon: {
      species: string;
      where: string;
      state: string;
      detail: string;
    }[];
  } | null>(null);
  return (
    <section className="panel import-tools">
      <h2>Import into your Bank</h2>
      <p className="muted">
        Choose a Pokémon file or game save. The source stays unchanged. Imports
        use pokeldn’s existing validation and conversion rules; review every
        result below.
      </p>
      {!ready && (
        <p className="filter-message">
          PKHeX is unavailable. Build the helper on your Pi before importing.
        </p>
      )}
      <label>
        Pokémon file or save
        <input
          type="file"
          disabled={busy || !ready}
          onChange={async (e) => {
            const input = e.currentTarget,
              file = input.files?.[0];
            if (!file) return;
            setError("");
            setResult(null);
            if (file.size > 64 * 1024 * 1024) {
              setError("The import limit is 64 MiB.");
              return;
            }
            setBusy(true);
            try {
              setResult(
                await api(`/api/import?name=${encodeURIComponent(file.name)}`, {
                  method: "POST",
                  headers: { "Content-Type": "application/octet-stream" },
                  body: file,
                }),
              );
              onChange();
            } catch (err) {
              setError((err as Error).message);
            } finally {
              setBusy(false);
              input.value = "";
            }
          }}
        />
      </label>
      {busy && (
        <p role="status">Validating and importing… Keep this page open.</p>
      )}
      {error && <p role="alert">{error}</p>}
      {result && (
        <div role="status">
          <strong>
            {result.name}
            {result.save && ` · ${result.save}`}
          </strong>
          <p>
            {result.pokemon.filter((p) => p.state === "banked").length} banked ·{" "}
            {result.pokemon.filter((p) => p.state === "already").length} already
            imported ·{" "}
            {result.pokemon.filter((p) => p.state === "refused").length} refused
          </p>
          <ul>
            {result.pokemon.map((p, i) => (
              <li key={i}>
                {p.species} {p.where} — {p.state}
                {p.detail && `: ${p.detail}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
export function MoveTools({
  pokemon,
  boxes,
  onChange,
  onClose,
}: {
  pokemon: Pokemon;
  boxes: Box[];
  onChange: () => void;
  onClose: () => void;
}) {
  const [boxId, setBoxId] = useState(boxes[0].id),
    [slot, setSlot] = useState(1),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  return (
    <div className="move-tools">
      <a
        className="primary"
        href={`/api/pokemon/${encodeURIComponent(pokemon.id)}/export`}
      >
        Export Pokémon file
      </a>
      <p className="muted">
        Exports the stored record. Exporting leaves the Pokémon in your Bank.
      </p>
      <label>
        Destination box
        <select
          value={boxId}
          onChange={(e) => setBoxId(Number(e.target.value))}
        >
          {boxes.filter(b => b.kind !== "dummy").map((b) => (
            <option value={b.id} key={b.id}>
              {b.name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Destination slot (1–30)
        <input
          aria-label="Destination slot"
          type="number"
          min={1}
          max={30}
          value={slot}
          onChange={(e) => setSlot(Number(e.target.value))}
        />
      </label>
      <p className="muted">An occupied destination swaps the two Pokémon.</p>
      <button
        disabled={busy || slot < 1 || slot > 30 || !Number.isInteger(slot)}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await api(`/api/pokemon/${encodeURIComponent(pokemon.id)}/move`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                box_id: boxId,
                slot: slot - 1,
                expected:
                  boxes.find((b) => b.id === boxId)?.slots[slot - 1]?.id ??
                  null,
              }),
            });
            onChange();
            onClose();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        Move / swap Pokémon
      </button>
      {error && <p role="alert">{error}</p>}
    </div>
  );
}
export function RenameBox({
  box,
  onChange,
}: {
  box: Box;
  onChange: () => void;
}) {
  const [name, setName] = useState(box.name),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    setName(box.name);
    setError("");
  }, [box.id, box.name]);
  return (
    <form
      className="rename-box"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError("");
        try {
          await api(`/api/boxes/${box.id}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name }),
          });
          onChange();
        } catch (err) {
          setError((err as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label>
        Box name
        <input
          value={name}
          maxLength={32}
          required
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      <button disabled={busy}>Rename box</button>
      {error && <span role="alert">{error}</span>}
    </form>
  );
}
export function StorageSettings({ onChange }: { onChange: () => void }) {
  const [trainer, setTrainer] = useState<Trainer>({
    ot: "",
    tid: 0,
    sid: 0,
    language: 2,
    gender: 0,
  });
  const [backups, setBackups] = useState<Backup[]>([]),
    [message, setMessage] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const refresh = async () => {
    const [settings, snapshots] = await Promise.all([
      api("/api/settings"),
      api("/api/backups"),
    ]);
    if (settings.trainer) setTrainer(settings.trainer);
    setBackups(snapshots);
  };
  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, []);
  return (
    <section className="panel">
      <h2>Receiving trainer</h2>
      <p className="muted">
        Required before import. Older records can be converted by the original
        Bank importer; these values identify the receiving handler. The original
        trainer is preserved by upstream conversion rules. IDs are the
        underlying 16-bit TID/SID, not the six-digit display ID.
      </p>
      <form
        className="trainer-form"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError("");
          try {
            await api("/api/settings/trainer", {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(trainer),
            });
            setMessage("Receiving trainer saved.");
            await refresh();
            onChange();
          } catch (err) {
            setError((err as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <label>
          Trainer name
          <input
            required
            maxLength={12}
            value={trainer.ot}
            onChange={(e) => setTrainer({ ...trainer, ot: e.target.value })}
          />
        </label>
        {(["tid", "sid"] as const).map((key) => (
          <label key={key}>
            {key.toUpperCase()} (0–65535)
            <input
              required
              type="number"
              min={0}
              max={65535}
              value={trainer[key]}
              onChange={(e) =>
                setTrainer({ ...trainer, [key]: Number(e.target.value) })
              }
            />
          </label>
        ))}
        <label>
          Language
          <select
            value={trainer.language}
            onChange={(e) =>
              setTrainer({ ...trainer, language: Number(e.target.value) })
            }
          >
            {[
              [1, "Japanese"],
              [2, "English"],
              [3, "French"],
              [4, "Italian"],
              [5, "German"],
              [7, "Spanish"],
              [8, "Korean"],
              [9, "Chinese (Simplified)"],
              [10, "Chinese (Traditional)"],
            ].map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Trainer gender
          <select
            value={trainer.gender}
            onChange={(e) =>
              setTrainer({ ...trainer, gender: Number(e.target.value) })
            }
          >
            <option value={0}>Male</option>
            <option value={1}>Female</option>
          </select>
        </label>
        <button className="primary" disabled={busy}>
          Save receiving trainer
        </button>
      </form>
      {message && <p role="status">{message}</p>}
      {error && <p role="alert">{error}</p>}
      <div className="backup-tools">
        <h2>Backups and recovery</h2>
        <p className="muted">
          Each change creates an immutable snapshot on the Pi. Download a copy
          to another device before testing imports. Snapshots are retained;
          monitor free disk space.
        </p>
        <a className="primary" href="/api/backup">
          Download current backup ZIP
        </a>
        <p className="muted">
          Restoring a snapshot changes box contents and trainer settings. Your
          current snapshot remains available for recovery.
        </p>
        {backups.map((b) => (
          <div className="backup-row" key={b.id}>
            <span>
              {new Date(b.time * 1000).toLocaleString()}
              <small>{b.action}</small>
            </span>
            <button
              disabled={busy || b.current || b.valid === false}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  await api(`/api/backups/${b.id}/restore`, { method: "POST" });
                  setMessage("Backup restored as a new snapshot.");
                  await refresh();
                  onChange();
                } catch (err) {
                  setError((err as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              {b.valid === false
                ? "Unavailable"
                : b.current
                  ? "Current"
                  : "Restore snapshot"}
            </button>
          </div>
        ))}
      </div>
    </section>
  );
}
export function StorageHistory() {
  const [events, setEvents] = useState<Event[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    api("/api/history")
      .then((data) => setEvents(data.entries))
      .catch((err) => setError(err.message));
  }, []);
  return (
    <section className="panel">
      <h2>Bank activity</h2>
      <p className="muted">
        Bank and simulation activity. Real Switch trading is not connected.
      </p>
      {error && <p role="alert">{error}</p>}
      {!events.length && <p>No storage operations yet.</p>}
      {events.map((e) => (
        <div className="backup-row" key={e.id}>
          <span>{e.action}</span>
          <time>{new Date(e.time * 1000).toLocaleString()}</time>
        </div>
      ))}
    </section>
  );
}
