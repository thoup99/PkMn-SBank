import { useEffect, useRef, useState } from "react";
import type { Box, Page, Pokemon } from "./types";
import Trading from "./Trading";
import USBTrading from "./USBTrading";
import KeysSettings from "./KeysSettings";
import ESP32 from "./ESP32";
import { matches, pageFromHash } from "./types";
import {
  ImportTools,
  MoveTools,
  RenameBox,
  StorageHistory,
  StorageSettings,
} from "./BankTools";

interface Hardware {
  hardware_connected: boolean;
  hardware_status: "connected" | "disconnected" | "unsupported" | "unavailable" | "demo";
  devices: {device: string; description: string}[];
}
const unknownHardware: Hardware = {hardware_connected:false, hardware_status:"unavailable", devices:[]};

const pages: [Page, string, string][] = [
  ["dashboard", "Dashboard", "◈"],
  ["boxes", "Pokémon boxes", "▦"],
  ["trading", "Trading", "⇄"],
  ["history", "History", "◷"],
  ["esp32", "ESP32", "▣"],
  ["settings", "Settings", "⚙"],
];
const types = [
  "Electric",
  "Fairy",
  "Fighting",
  "Fire",
  "Flying",
  "Ghost",
  "Grass",
  "Normal",
  "Poison",
  "Psychic",
  "Steel",
  "Water",
  "Dragon",
];
function Sprite({ pokemon }: { pokemon: Pokemon }) {
  const [imageStage, setImageStage] = useState(0);
  return imageStage >= 2 ? (
    <span className="sprite-fallback" aria-label={pokemon.species}>
      {pokemon.species.slice(0, 2)}
    </span>
  ) : (
    <img
      className="sprite"
      src={
        imageStage === 0
          ? `/sprites/${pokemon.shiny ? "shiny/" : ""}${pokemon.dex}.png`
          : `/api/sprites/${pokemon.dex}?shiny=${pokemon.shiny}`
      }
      alt={pokemon.species}
      onError={() => setImageStage((s) => s + 1)}
    />
  );
}
function Details({
  pokemon,
  onClose,
  demo,
  boxes,
  onChange,
}: {
  pokemon: Pokemon;
  onClose: () => void;
  demo: boolean;
  boxes: Box[];
  onChange: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current!;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={onClose}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      aria-labelledby="detail-title"
    >
      <button
        className="close"
        aria-label="Close Pokémon details"
        onClick={onClose}
      >
        ×
      </button>
      <p className="eyebrow">
        POKÉMON DETAILS · {demo ? "SAMPLE" : "BANK RECORD"}
      </p>
      <div className="detail-sprite">
        <Sprite pokemon={pokemon} />
      </div>
      <h2 id="detail-title">
        {pokemon.species} {pokemon.shiny && "✦"}
      </h2>
      <p>
        #{String(pokemon.dex).padStart(4, "0")} · Level{" "}
        {pokemon.level ?? "unknown"}
      </p>
      <div className="tags">
        {pokemon.types.map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
      <dl>
        {[
          ["Nature", pokemon.nature],
          ["Ability", pokemon.ability],
          ["Original trainer", pokemon.trainer],
          ["Source game", pokemon.game],
        ].map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v || "Not recorded"}</dd>
          </div>
        ))}
      </dl>
      <p className="muted">
        {demo
          ? "Illustrative metadata only. This is not a stored Pokémon record."
          : pokemon.summary}
      </p>
      {!demo && (
        <>
          <p className="muted">
            Import validation:{" "}
            {pokemon.legal
              ? "accepted by the Bank importer"
              : "not marked legal"}
            {pokemon.home_tracker && ` · HOME tracker: ${pokemon.home_tracker}`}
            . Destination compatibility is checked in a later phase.
          </p>
          <MoveTools
            pokemon={pokemon}
            boxes={boxes}
            onChange={onChange}
            onClose={onClose}
          />
        </>
      )}
      <button className="primary" onClick={onClose}>
        Back to boxes
      </button>
    </dialog>
  );
}
export default function App() {
  const [page, setPage] = useState<Page>(pageFromHash);
  const [boxes, setBoxes] = useState<Box[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">(
    "loading",
  );
  const [attempt, setAttempt] = useState(0);
  const [active, setActive] = useState(1);
  const [query, setQuery] = useState("");
  const [type, setType] = useState("");
  const [selected, setSelected] = useState<Pokemon | null>(null);
  const [compact, setCompact] = useState(false);
  const [demo, setDemo] = useState(false);
  const [pkhex, setPkhex] = useState(false);
  const [hardware, setHardware] = useState<Hardware | null>(null);
  const reload = () => setAttempt((a) => a + 1);
  const [game, setGame] = useState("Sword / Shield");
  useEffect(() => {
    const update = () => {
      setPage(pageFromHash());
      setSelected(null);
    };
    window.addEventListener("hashchange", update);
    return () => window.removeEventListener("hashchange", update);
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    if (!boxes.length) setStatus("loading");
    Promise.all([
      fetch("/api/boxes", { signal: controller.signal }),
      fetch("/api/health", { signal: controller.signal }),
    ])
      .then(async ([response, health]) => {
        if (!response.ok || !health.ok) throw new Error("Unable to load boxes");
        const info = await health.json();
        setDemo(info.mode === "demo");
        setPkhex(info.pkhex_available);
        setHardware(info.mode === "demo" ? {...unknownHardware, hardware_status:"demo"} : info.hardware_status ? info : null);
        return response.json();
      })
      .then((data: Box[]) => {
        if (
          !Array.isArray(data) ||
          !data.length ||
          data.some((b) => !Array.isArray(b.slots) || b.slots.length !== 30)
        )
          throw new Error("Invalid box data");
        setBoxes(data);
        setStatus("ready");
      })
      .catch(() => {
        if (!controller.signal.aborted) setStatus("error");
      });
    return () => controller.abort();
  }, [attempt]);
  useEffect(() => {
    if (status !== "ready" || demo) return;
    let mounted = true, pending = false;
    const controller = new AbortController();
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch("/api/hardware", {signal: controller.signal, cache:"no-store"});
        if (!response.ok) throw new Error("USB status unavailable");
        const value: Hardware = await response.json();
        if (!Array.isArray(value.devices) || !["connected", "disconnected", "unsupported", "unavailable", "demo"].includes(value.hardware_status))
          throw new Error("Invalid USB status");
        if (mounted) setHardware(value);
      } catch {
        if (mounted) setHardware(unknownHardware);
      } finally {pending = false;}
    };
    const visible = () => {if (!document.hidden) refresh();};
    refresh();
    const timer = window.setInterval(refresh, 3000);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", visible);
    return () => {
      mounted = false; controller.abort(); window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [status, demo]);
  const hardwareState = demo ? "demo" : hardware?.hardware_status;
  const hardwareLabel = hardwareState === "connected" ? "Connected" : hardwareState === "disconnected" ? "Disconnected"
    : hardwareState === "demo" ? "Demo mode" : hardwareState === "unsupported" ? "Unsupported host" : hardware ? "Status unavailable" : "Checking…";
  const box = boxes.find((b) => b.id === active) ?? boxes[0];
  const all = boxes
    .flatMap((b) => b.slots)
    .filter((p): p is Pokemon => !!p);
  const count = box?.slots.filter(Boolean).length ?? 0;
  const visible =
    box?.slots.filter((p) => p && matches(p, query, type)).length ?? 0;
  const changeBox = (id: number) => {
    setActive(id);
    setSelected(null);
  };
  return (
    <div className={compact ? "app compact" : "app"}>
      <aside className="sidebar">
        <a className="brand" href="#dashboard">
          <span className="brand-mark">S</span>
          <span>
            PkMn-SBank<small>YOUR NEXT GENERATION</small>
          </span>
        </a>
        <nav aria-label="Main navigation">
          {pages.map(([id, label, icon]) => (
            <a
              key={id}
              href={`#${id}`}
              className={page === id ? "active" : ""}
              aria-current={page === id ? "page" : undefined}
            >
              <span aria-hidden="true">{icon}</span>
              {label}
            </a>
          ))}
        </nav>
        <div className="host">
          <span className={`status-dot hardware-${hardwareState || "checking"}`} /> {demo ? "Website demo" : "Local Bank"}
          <small>Raspberry Pi 5 host</small>
          <span className="host-tag" role="status" aria-label="Sidebar hardware status">USB · {hardwareLabel}</span>
        </div>
        <p className="sidebar-foot">A bridge to your next adventure.</p>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <span>YOUR POKÉMON. NEW POSSIBILITIES.</span>
          <span className="demo-pill">
            {demo ? "Sample data" : "Your Bank"}
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <p className="eyebrow">PKMN SUPER BANK / {page.toUpperCase()}</p>
              <h1>{pages.find(([id]) => id === page)?.[1]}</h1>
              <p className="subtitle">
                {page === "boxes"
                  ? "A familiar place for your next move."
                  : "Your Pokémon transfer bridge, at a glance."}
              </p>
            </div>
            <span className="version">{demo ? "READ-ONLY DEMO" : "LOCAL BANK · USB TRADING"}</span>
          </div>
          <div className="notice">
            <span aria-hidden="true">◉</span>
            <span>
              {demo ? (
                <>
                  <strong>You’re exploring the demo.</strong> Sample Pokémon
                  only.
                </>
              ) : (
                <>
                  <strong>Your Bank lives on this Pi.</strong> Imports, box
                  changes, and backups are saved locally. Set your receiving
                  trainer in Settings before importing.
                </>
              )}{" "}
              {demo ? "No real trades run in demo mode." : "Use Trading to start a local Switch trade."}
            </span>
          </div>
          {status === "loading" && (
            <section className="panel empty" role="status">
              Loading boxes…
            </section>
          )}
          {status === "error" && (
            <section className="panel empty" role="alert">
              <h2>Couldn’t load the boxes</h2>
              <p>Check that the FastAPI server is running, then try again.</p>
              <button
                className="primary"
                onClick={() => setAttempt((a) => a + 1)}
              >
                Retry
              </button>
            </section>
          )}
          {status === "ready" && page === "dashboard" && (
            <>
              <section className="hero">
                <div>
                  <p className="eyebrow">READY FOR THE NEXT ADVENTURE</p>
                  <h2>
                    From one journey
                    <br />
                    to the next.
                  </h2>
                  <p>
                    Explore your staging boxes and find your favorites.
                    <br />A new home base for the Pokémon you take along.
                  </p>
                  <a className="primary" href="#boxes">
                    Open Pokémon boxes <span aria-hidden="true">↗</span>
                  </a>
                </div>
                <div className="hero-art" aria-hidden="true">
                  <div className="orb" />
                  <span className="orbit-label">CONNECT. STAGE. TRANSFER.</span>
                </div>
              </section>
              <section className="stats" aria-label="Bank summary">
                <div>
                  <span>{demo ? "Sample Pokémon" : "Banked Pokémon"}</span>
                  <strong>{all.length.toString().padStart(2, "0")}</strong>
                  <small>
                    {demo ? "Illustrative records" : "Saved on your Pi"}
                  </small>
                </div>
                <div>
                  <span>Staging boxes</span>
                  <strong>{boxes.length.toString().padStart(2, "0")}</strong>
                  <small>30 slots in each box</small>
                </div>
                <div>
                  <span>Hardware</span>
                  <strong className="text-stat" role="status" aria-label="Dashboard hardware status">{hardwareLabel}</strong>
                  <small>{hardwareState === "connected" ? `${hardware?.devices.length || 0} native USB port(s) detected` : hardwareState === "demo" ? "Live hardware checks are disabled" : hardwareState === "disconnected" ? "Connect the board via native USB" : "Check the ESP32 page for setup"}</small>
                  {hardwareState === "connected" && <small>USB detection only; radio and Switch link not verified</small>}
                </div>
              </section>
              <section className="panel">
                <div className="section-heading">
                  <h2>Your boxes</h2>
                  <a href="#boxes">View all →</a>
                </div>
                <div className="box-cards">
                  {boxes.map((b) => (
                    <a key={b.id} href="#boxes" onClick={() => changeBox(b.id)}>
                      <span className="box-icon">▦</span>
                      <strong>{b.name}</strong>
                      <small>
                        {b.slots.filter(Boolean).length} / 30 Pokémon
                      </small>
                      <span className="mini-slots">
                        {Array.from({ length: 10 }, (_, i) => (
                          <i
                            key={i}
                            className={
                              i < b.slots.filter(Boolean).length ? "filled" : ""
                            }
                          />
                        ))}
                      </span>
                    </a>
                  ))}
                </div>
              </section>
            </>
          )}
          {status === "ready" && page === "boxes" && box && (
            <>
              <section className="panel boxes-panel">
                <div className="section-heading">
                  <div>
                    <h2>{box.name}</h2>
                    <p className="muted">
                      Box {box.id.toString().padStart(2, "0")} · {count} / 30
                      occupied{(query || type) && ` · ${visible} matching`}
                    </p>
                  </div>
                  <div className="box-stepper">
                    <button
                      aria-label="Previous box"
                      disabled={boxes[0].id === box.id}
                      onClick={() => changeBox(box.id - 1)}
                    >
                      ←
                    </button>
                    <label className="sr-only" htmlFor="box-select">
                      Select box
                    </label>
                    <select
                      id="box-select"
                      value={box.id}
                      onChange={(e) => changeBox(Number(e.target.value))}
                    >
                      {boxes.map((b) => (
                        <option key={b.id} value={b.id}>
                          {b.name}
                        </option>
                      ))}
                    </select>
                    <button
                      aria-label="Next box"
                      disabled={boxes[boxes.length - 1].id === box.id}
                      onClick={() => changeBox(box.id + 1)}
                    >
                      →
                    </button>
                  </div>
                </div>
                {!demo && (
                  <RenameBox box={box} onChange={reload} />
                )}
                <div className="filters">
                  <label className="search">
                    <span aria-hidden="true">⌕</span>
                    <input
                      aria-label="Search Pokémon"
                      placeholder="Search name, Pokédex number, or game…"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                    />
                  </label>
                  <label className="sr-only" htmlFor="type">
                    {demo ? "Filter by type" : "Filter by game"}
                  </label>
                  <select
                    id="type"
                    value={type}
                    onChange={(e) => setType(e.target.value)}
                  >
                    <option value="">{demo ? "All types" : "All games"}</option>
                    {(demo ? types : [...new Set(all.map((p) => p.game))])
                      .sort()
                      .map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                  </select>
                  {(query || type) && (
                    <button
                      onClick={() => {
                        setQuery("");
                        setType("");
                      }}
                    >
                      Clear filters
                    </button>
                  )}
                </div>
                {(query || type) && visible === 0 && (
                  <p role="status" className="filter-message">
                    No matching Pokémon in this box. Try another box or clear
                    the filters.
                  </p>
                )}
                <div className="box-grid" aria-label={`${box.name}, 30 slots`}>
                  {box.slots.map((pokemon, i) => {
                    const hidden = pokemon && !matches(pokemon, query, type);
                    return (
                      <div
                        className={`slot ${pokemon ? "occupied" : ""} ${hidden ? "filtered" : ""}`}
                        key={i}
                      >
                        <span className="slot-number">
                          {String(i + 1).padStart(2, "0")}
                        </span>
                        {pokemon ? (
                          <button
                            disabled={!!hidden}
                            onClick={() => setSelected(pokemon)}
                            aria-label={`View ${pokemon.species}, level ${pokemon.level ?? "unknown"}, slot ${i + 1}`}
                          >
                            <Sprite pokemon={pokemon} />
                            <strong>{pokemon.species}</strong>
                            <small>
                              Lv. {pokemon.level ?? "?"}{" "}
                              {pokemon.shiny && (
                                <span className="shiny" aria-label="Shiny">
                                  ✦
                                </span>
                              )}
                            </small>
                          </button>
                        ) : (
                          <span
                            className="empty-slot"
                            aria-label={`Empty slot ${i + 1}`}
                          >
                            ＋
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
                <div className="box-footer">
                  <span>
                    <span className="status-dot" />{" "}
                    {demo ? "Sample staging box" : "Saved staging box"}
                  </span>
                  <span>Select a Pokémon to view details</span>
                </div>
              </section>
              {!demo && (
                <ImportTools ready={pkhex} onChange={reload} />
              )}
            </>
          )}
          {status === "ready" && page === "trading" && !demo && (
            <>
              <USBTrading boxes={boxes} onChange={reload} />
              <Trading boxes={boxes} ready={pkhex} />
            </>
          )}
          {status === "ready" && page === "trading" && demo && (
            <section className="panel trading">
              <p className="eyebrow">PLAN YOUR NEXT MOVE</p>
              <h2>Switch trading</h2>
              <p>
                The original pokeldn trading tools are preserved. Website
                session controls will be connected in the next phase.
              </p>
              <label htmlFor="game">Preview a destination</label>
              <select
                id="game"
                value={game}
                onChange={(e) => setGame(e.target.value)}
              >
                {[
                  "Sword / Shield",
                  "Scarlet / Violet",
                  "Brilliant Diamond / Shining Pearl",
                  "Legends Arceus",
                  "Let's Go",
                  "Legends Z-A",
                  "FireRed / LeafGreen",
                ].map((g) => (
                  <option key={g}>{g}</option>
                ))}
              </select>
              <div className="transfer-path">
                <div>
                  ▦<strong>Staging box</strong>
                  <small>{demo ? "Sample Pokémon" : "Banked Pokémon"}</small>
                </div>
                <span>→</span>
                <div>
                  ◇<strong>{game}</strong>
                  <small>Not connected</small>
                </div>
              </div>
              <button disabled>Trading is not connected</button>
              <p className="muted">
                No session is started and no compatibility validation is
                performed in this preview.
              </p>
            </section>
          )}
          {status === "ready" && page === "history" && !demo && (
            <StorageHistory />
          )}
          {status === "ready" && page === "history" && demo && (
            <section className="panel empty">
              <span className="empty-icon">◷</span>
              <h2>A fresh start</h2>
              <p>
                No real transfers have been performed. Completed transfers and
                recovery information will appear here when trading is connected.
              </p>
              <a className="primary" href="#boxes">
                Explore sample boxes
              </a>
            </section>
          )}
          {status === "ready" && page === "esp32" && <ESP32 demo={demo} />}
          {status === "ready" && page === "settings" && (
            <>
              {!demo && <KeysSettings />}
              <section className="panel settings">
                <h2>Website preferences</h2>
                <p className="muted">
                  Appearance controls apply to this browser session.
                </p>
                <label className="setting-row">
                  <span>
                    <strong>Compact boxes</strong>
                    <small>Reduce space between Pokémon slots</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={compact}
                    onChange={(e) => setCompact(e.target.checked)}
                  />
                </label>
                <div className="setting-row">
                  <span>
                    <strong>Data source</strong>
                    <small>
                      {demo
                        ? "Read-only samples"
                        : "Persistent Bank on your Raspberry Pi 5"}
                    </small>
                  </span>
                  <span className="demo-pill">
                    {demo ? "Demo" : "Local Bank"}
                  </span>
                </div>
                <div className="setting-row">
                  <span>
                    <strong>Host architecture</strong>
                    <small>Raspberry Pi 5 → USB → ESP32-S3</small>
                  </span>
                </div>
                <p className="muted">
                  Upload your Switch keys below. Real USB trade controls are on the Trading page.
                </p>
              </section>
              {!demo && <StorageSettings onChange={reload} />}
            </>
          )}
          <footer>
            <span>PkMn-SBank · An unofficial fan project</span>
            <span>A temporary stop. A new adventure.</span>
          </footer>
        </main>
      </div>
      {selected && (
        <Details
          key={selected.id}
          pokemon={selected}
          demo={demo}
          boxes={boxes}
          onChange={reload}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
}
