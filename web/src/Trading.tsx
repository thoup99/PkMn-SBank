import { useEffect, useState } from "react";
import { api } from "./BankTools";
import type { Box } from "./types";
interface QueueItem {
  id: string;
  species: string;
  source_game: string;
  compatible: boolean;
  reason: string;
  warnings: string[];
}
interface Preview {
  game: string;
  queue: QueueItem[];
  compatible: boolean;
  token: string;
}
interface Session {
  id: string;
  mode: "simulation";
  game: string;
  status: string;
  version: number;
  queue: QueueItem[];
  completed: number;
  invalidated: boolean;
  events: { time: number; message: string }[];
}
interface Game {
  key: string;
  name: string;
}
const running = ["connecting", "waiting", "exchanging"];
export default function Trading({
  boxes,
  ready,
}: {
  boxes: Box[];
  ready: boolean;
}) {
  const [games, setGames] = useState<Game[]>([]),
    [game, setGame] = useState("swsh");
  const [selected, setSelected] = useState<string[]>([]),
    [query, setQuery] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null),
    [session, setSession] = useState<Session | null>(null);
  const [scenario, setScenario] = useState("success"),
    [faultAfter, setFaultAfter] = useState(0);
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [loaded, setLoaded] = useState(false);
  const bank = boxes.flatMap((b) => b.slots).filter((p) => p !== null);
  const active = !!session && running.includes(session.status);
  const refresh = async () => {
    const data = await api("/api/trade/session");
    setGames(data.games);
    setSession(data.session);
    if (data.session?.invalidated) { setSelected([]); setPreview(null); }
    return data;
  };
  useEffect(() => {
    let live = true;
    api("/api/trade/session")
      .then((data) => {
        if (!live) return;
        setGames(data.games);
        setSession(data.session);
        setLoaded(true);
        if (
          data.session && !data.session.invalidated &&
          [
            "ready",
            ...running,
            "disconnected",
            "failed",
            "interrupted",
          ].includes(data.session.status)
        ) {
          setSelected(data.session.queue.map((p: QueueItem) => p.id).filter((id: string) => bank.some(p => p.id === id)));
          setGame(data.session.game);
        }
      })
      .catch((err) => {
        if (live) {
          setError(err.message);
          setLoaded(true);
        }
      });
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    if (!active || busy) return;
    let live = true;
    const timer = window.setInterval(() => {
      api("/api/trade/session")
        .then((data) => {
          if (live) {
            if (data.session?.invalidated) { setSelected([]); setPreview(null); }
            setSession((current) =>
              current?.id === data.session?.id &&
              current!.version > data.session.version
                ? current
                : data.session,
            );
          }
        })
        .catch((err) => {
          if (live) setError(err.message);
        });
    }, 2500);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [active, busy]);
  const perform = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (err) {
      setError((err as Error).message);
      try {
        await refresh();
      } catch {
        /* Keep the original error visible. */
      }
    } finally {
      setBusy(false);
    }
  };
  const action = (name: string) =>
    perform(async () => {
      if (!session) return;
      const next = await api(`/api/trade/session/${session.id}/${name}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          version: session.version,
          scenario,
          fault_after: faultAfter,
        }),
      });
      setSession(next);
    });
  return (
    <>
      <section className="panel trading-workflow">
        <p className="eyebrow">PHASE 4 · SIMULATION</p>
        <h2>Prepare a trade</h2>
        <p className="muted">
          Compatibility uses PKHeX and your receiving trainer. The partner and
          confirmations are simulated. No Switch, ESP32-S3, or real transfer is
          connected; every original Pokémon stays in your Bank.
        </p>
        {!ready && (
          <p className="filter-message">
            Build the PKHeX helper before checking compatibility.
          </p>
        )}
        {error && <p role="alert">{error}</p>}
        {!loaded && <p role="status">Loading simulation…</p>}
        {loaded && !games.length && (
          <button
            disabled={busy}
            onClick={() =>
              perform(async () => {
                await refresh();
              })
            }
          >
            Retry loading trading
          </button>
        )}
        <label className="trade-field">
          Destination game
          <select
            value={game}
            disabled={busy || active || !loaded}
            onChange={(e) => {
              setGame(e.target.value);
              setPreview(null);
            }}
          >
            {games.map((g) => (
              <option key={g.key} value={g.key}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
        <label className="trade-field">
          Search Bank for staging
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Name or source game"
          />
        </label>
        <p className="muted">
          Choose up to six Pokémon in queue order. Selected: {selected.length}
          /6.
        </p>
        {!bank.length && (
          <p>
            Import Pokémon in Boxes and set your receiving trainer in Settings
            first.
          </p>
        )}
        <div className="stage-list">
          {bank
            .filter((p) =>
              `${p.species} ${p.game}`
                .toLowerCase()
                .includes(query.toLowerCase()),
            )
            .map((p) => (
              <label key={p.id}>
                <input
                  type="checkbox"
                  checked={selected.includes(p.id)}
                  disabled={
                    busy ||
                    active ||
                    (!selected.includes(p.id) && selected.length === 6)
                  }
                  onChange={(e) => {
                    setSelected((ids) =>
                      e.target.checked
                        ? [...ids, p.id]
                        : ids.filter((id) => id !== p.id),
                    );
                    setPreview(null);
                  }}
                />
                <span>
                  <strong>{p.species}</strong>
                  <small>
                    Lv. {p.level ?? "?"} · {p.game}
                    {selected.includes(p.id) &&
                      ` · Queue ${selected.indexOf(p.id) + 1}`}
                  </small>
                </span>
              </label>
            ))}
        </div>
        <div className="trade-actions">
          <button disabled={busy || active || !selected.length} onClick={()=>{setSelected([]);setPreview(null);}}>Clear selection</button>
          <button
            disabled={
              !ready ||
              !loaded ||
              !games.length ||
              busy ||
              active ||
              !selected.length
            }
            onClick={() =>
              perform(async () => {
                setPreview(
                  await api("/api/trade/preview", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ game, entry_ids: selected }),
                  }),
                );
              })
            }
          >
            Check compatibility
          </button>
          <button
            className="primary"
            disabled={busy || active || !preview?.compatible}
            onClick={() =>
              perform(async () => {
                if (!preview) return;
                setSession(
                  await api("/api/trade/stage", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      game,
                      entry_ids: selected,
                      token: preview.token,
                    }),
                  }),
                );
                setPreview(null);
                setFaultAfter(0);
              })
            }
          >
            Stage simulation queue
          </button>
        </div>
        {busy && <p role="status">Checking or saving simulation…</p>}
        {preview && (
          <div
            className="compatibility-results"
            aria-label="Compatibility results"
          >
            {preview.queue.map((p) => (
              <div key={p.id}>
                <strong>
                  {p.species} — {p.compatible ? "Compatible" : "Refused"}
                </strong>
                {p.reason && <p>{p.reason}</p>}
                {p.warnings.map((w, i) => (
                  <p className="muted" key={i}>
                    {w}
                  </p>
                ))}
              </div>
            ))}
          </div>
        )}
      </section>
      {session && (
        <section className="panel session-panel">
          <div className="section-heading">
            <h2>Simulated session</h2>
            <span className="demo-pill">{session.status}</span>
          </div>
          <p>
            {games.find((g) => g.key === session.game)?.name ?? session.game} ·{" "}
            {session.queue.map((p) => p.species).join(" → ")}
          </p>
          <label className="trade-field">
            Simulated confirmations: {session.completed}/{session.queue.length}
            <progress
              aria-label="Simulated confirmations"
              value={session.completed}
              max={session.queue.length}
            />
          </label>
          <p className="muted">
            These are simulated confirmations. Real transfers: 0. Original Bank
            records retained: {session.queue.length}/{session.queue.length}.
          </p>
          {session.status === "ready" && (
            <div className="scenario-controls">
              <label className="trade-field">
                Simulation scenario
                <select
                  value={scenario}
                  disabled={busy}
                  onChange={(e) => setScenario(e.target.value)}
                >
                  <option value="success">Success</option>
                  <option value="disconnect">
                    Disconnect before confirmation
                  </option>
                  <option value="failure">Failure before confirmation</option>
                </select>
              </label>
              {scenario !== "success" && (
                <label className="trade-field">
                  Confirmations before fault
                  <select
                    value={faultAfter}
                    disabled={busy}
                    onChange={(e) => setFaultAfter(Number(e.target.value))}
                  >
                    {session.queue.map((_, i) => (
                      <option key={i} value={i}>
                        {i}
                      </option>
                    ))}
                  </select>
                </label>
              )}
            </div>
          )}
          <div className="trade-actions">
            {session.status === "ready" && (
              <button
                className="primary"
                disabled={busy || !ready}
                onClick={() => action("start")}
              >
                Start simulation
              </button>
            )}
            {active && (
              <button
                className="primary"
                disabled={busy}
                onClick={() => action("advance")}
              >
                Advance simulation
              </button>
            )}
            {["disconnected", "failed", "interrupted"].includes(
              session.status,
            ) &&
              !session.invalidated && (
                <button
                  className="primary"
                  disabled={busy || !ready}
                  onClick={() => action("resume")}
                >
                  Resume simulation
                </button>
              )}
            {[
              "ready",
              ...running,
              "disconnected",
              "failed",
              "interrupted",
            ].includes(session.status) && (
              <button disabled={busy} onClick={() => action("cancel")}>
                Cancel simulation
              </button>
            )}
            <button
              disabled={busy}
              onClick={() =>
                perform(async () => {
                  await refresh();
                })
              }
            >
              Refresh session status
            </button>
          </div>
          {active && (
            <p className="muted">
              Use Advance simulation to supply the next synthetic connection,
              partner-ready or confirmation event. Status updates are saved
              after each step.
            </p>
          )}
          {session.invalidated && (
            <p className="filter-message">
              Bank recovery invalidated this session. Check compatibility and
              stage a fresh queue.
            </p>
          )}
          {[
            "completed",
            "cancelled",
            "disconnected",
            "failed",
            "interrupted",
          ].includes(session.status) && (
            <p role="status">
              {session.status === "completed"
                ? "Simulation completed."
                : "Simulation stopped."}{" "}
              All original Bank records remain unchanged.
            </p>
          )}
          <ol className="session-log" aria-label="Simulation log">
            {session.events.map((event, i) => (
              <li key={i}>
                <time>{new Date(event.time * 1000).toLocaleTimeString()}</time>{" "}
                {event.message}
              </li>
            ))}
          </ol>
        </section>
      )}
    </>
  );
}
