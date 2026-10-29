import { useEffect, useState } from "react";
import { api } from "./BankTools";
import type { Box } from "./types";
import { GENERATED_PIKACHU_ID as GENERATED_ID, isGeneratedPikachu as generatedOffer } from "./types";
interface USBSession {
  id: string;
  status: string;
  message: string;
  code: string;
  game: string;
  entry_id: string;
  species: string;
  received_id: string | null;
}
interface USBStatus {
  supported_host: boolean;
  keys_available: boolean;
  devices: { device: string; description: string }[];
  session: USBSession | null;
  logs: string[];
  games: { key: string; name: string; available: boolean }[];
}
interface Compatibility {
  game: string;
  entries: {id: string; compatible: boolean; reason: string}[];
}
const pending = [
  "starting",
  "running",
  "stopping",
  "interrupted",
  "uncertain",
  "recovery_required",
];
export function newRequestId() {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = Array.from(bytes, b => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}

export default function USBTrading({
  boxes,
  onChange,
}: {
  boxes: Box[];
  onChange: () => void;
}) {
  const [status, setStatus] = useState<USBStatus | null>(null),
    [game, setGame] = useState(""),
    [device, setDevice] = useState(""),
    [code, setCode] = useState("12345678"),
    [entry, setEntry] = useState("");
  const [useGenerated, setUseGenerated] = useState(false);
  const [compatibility, setCompatibility] = useState<Compatibility | null>(null);
  const [compatibilityError, setCompatibilityError] = useState("");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [checked, setChecked] = useState(false);
  const refresh = async () => {
    const result = await api("/api/usb/status");
    setStatus(result);
    if (result.session && pending.includes(result.session.status)) {
      setGame(result.session.game || result.game || "swsh");
      if (result.session.entry_id) {
        setUseGenerated(generatedOffer(result.session.entry_id));
        if (!generatedOffer(result.session.entry_id)) setEntry(result.session.entry_id);
      }
    }
    setDevice((current) => current || result.devices[0]?.device || "");
    return result;
  };
  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, []);
  useEffect(() => {
    setCompatibility(null);
    setCompatibilityError("");
    if (!game) return;
    let current = true;
    const controller = new AbortController();
    api(`/api/usb/compatibility?game=${encodeURIComponent(game)}`, {signal: controller.signal})
      .then((result: Compatibility) => {
        if (!current) return;
        if (result.game !== game || !Array.isArray(result.entries))
          throw new Error("Could not verify Pokémon compatibility. Refresh the page and try again.");
        setCompatibility(result);
        const bankIds = new Set(boxes.flatMap(box => box.slots).filter(p => p !== null).map(p => p.id));
        setEntry(previous => result.entries.some(item => item.id === previous && item.compatible && bankIds.has(item.id))
          ? previous : result.entries.find(item => item.compatible && bankIds.has(item.id))?.id || "");
      })
      .catch(err => {if (current) setCompatibilityError(err.message);});
    return () => {current = false; controller.abort();};
  }, [game, boxes]);
  useEffect(() => {
    if (!status?.session || !pending.includes(status.session.status) || busy)
      return;
    let live = true;
    const timer = window.setInterval(() => {
      api("/api/usb/status")
        .then((data) => {
          if (live) {
            setStatus(data);
            if (data.session?.status === "completed") onChange();
          }
        })
        .catch((err) => {
          if (live) setError(err.message);
        });
    }, 2000);
    return () => {
      live = false;
      window.clearInterval(timer);
    };
  }, [status?.session?.status, busy]);
  const perform = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await work();
      await refresh();
    } catch (err) {
      setError((err as Error).message);
      try {
        await refresh();
      } catch {}
    } finally {
      setBusy(false);
    }
  };
  const running =
      !!status?.session &&
      ["starting", "running", "stopping"].includes(status.session.status),
    blocked = !!status?.session && pending.includes(status.session.status);
  const available = new Map((compatibility?.game === game ? compatibility.entries : []).map(item => [item.id, item]));
  const sessionName = status?.games.find(target => target.key === status.session?.game)?.name;
  return (
    <section className="panel session-panel">
      <p className="eyebrow">REAL USB TRADE · SWORD / SHIELD · LEGENDS Z-A</p>
      <h2>Trade with your Switch</h2>
      <p className="muted">
        This starts one real Link Trade using the ESP32-S3 on your Pi’s native
        USB serial port. You can choose a Bank Pokémon or enable a generated Pikachu below. The
        received Pokémon is committed to boxes 1–4 after confirmation; a real
        outgoing Bank record leaves only in that same commit.
      </p>
      {error && <p role="alert">{error}</p>}
      {status && !status.supported_host && (
        <p className="filter-message">
          Live trading requires the Raspberry Pi 5 server.
        </p>
      )}
      {status && !status.keys_available && (
        <p className="filter-message">
          Upload your own Switch prod.keys in Settings or install them locally on the Pi.
        </p>
      )}
      <label className="trade-field">
        Destination game
        <select value={game} disabled={busy || blocked} onChange={e => setGame(e.target.value)}>
          <option value="">Choose destination game</option>
          {(status?.games || []).map(target => (
            <option key={target.key} value={target.key} disabled={!target.available}>
              {target.name}{target.available ? "" : " — live trading not connected yet"}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">Choose the game running on your Switch. Real USB trades currently support Sword / Shield and Legends Z-A. Other destinations can be previewed in the simulator below.</p>
      <label className="trade-field">
        Outgoing Pokémon
        <select
          className="outgoing-pokemon"
          value={entry}
          disabled={busy || blocked || useGenerated || !game || !compatibility || compatibility.game !== game}
          onChange={(e) => setEntry(e.target.value)}
        >
          <option value="">Choose an outgoing Pokémon</option>
          {boxes
            .flatMap((b) => b.slots)
            .filter((p) => p !== null)
            .map((p) => (
              <option value={p.id} key={p.id} disabled={!available.get(p.id)?.compatible} title={available.get(p.id)?.reason || undefined}>
                {p.species} ·{" "}
                {p.game} ·{" "}
                {p.id.slice(-8)}
                {available.get(p.id)?.compatible ? "" : ` — ${available.get(p.id)?.reason.replace(/\s+/g, " ").slice(0, 160) || "not checked"}`}
              </option>
            ))}
        </select>
      </label>
      <label className="setting-row generated-option">
        <input type="checkbox" checked={useGenerated}
          disabled={busy || blocked || (!useGenerated && !available.get(GENERATED_ID)?.compatible)}
          onChange={e => setUseGenerated(e.target.checked)} />
        <span>Use a valid generated Pikachu</span>
      </label>
      <p className="muted">A generated Pikachu is prepared and validated for the selected game, with a fresh identity for each trade. It does not occupy a Bank slot. Received Pokémon go into boxes 1–4.</p>
      {game && available.get(GENERATED_ID)?.reason && <p className="muted">Generated Pikachu: {available.get(GENERATED_ID)?.reason}</p>}
      {game && !compatibility && !compatibilityError && <p role="status">Checking Pokémon compatibility…</p>}
      {compatibilityError && <p role="alert">{compatibilityError}</p>}
      <p className="muted">Grayed-out Pokémon cannot be prepared for this game or have not been checked. Compatibility is revalidated before a real trade starts.</p>
      <label className="trade-field">
        Native USB board
        <select
          value={device}
          disabled={busy || blocked}
          onChange={(e) => setDevice(e.target.value)}
        >
          <option value="">Select attached board</option>
          {status?.devices.map((d) => (
            <option key={d.device} value={d.device}>
              {d.device} · {d.description}
            </option>
          ))}
        </select>
      </label>
      <p className="muted">
        Native Espressif USB IDs are shared by S3/C3/C6. Verify that you
        connected your ESP32-S3’s native USB port and installed the wireless
        radio firmware.
      </p>
      <label className="trade-field">
        Eight-digit Link Code
        <input
          value={code}
          maxLength={8}
          inputMode="numeric"
          disabled={busy || blocked}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
        />
      </label>
      <div className="trade-actions">
        <button
          disabled={busy}
          onClick={() =>
            perform(async () => {
              await refresh();
            })
          }
        >
          Refresh USB status
        </button>
        <button
          className="primary"
          disabled={
            busy ||
            blocked ||
            !status?.supported_host ||
            !status?.keys_available ||
            !available.get(useGenerated ? GENERATED_ID : entry)?.compatible ||
            !status?.games?.some(target => target.key === game && target.available) ||
            !device ||
            !/^\d{8}$/.test(code)
          }
          onClick={() =>
            perform(async () => {
              await api("/api/usb/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  game,
                  entry_id: useGenerated ? GENERATED_ID : entry,
                  device,
                  code,
                  request_id: newRequestId(),
                }),
              });
              setChecked(false);
            })
          }
        >
          {game === "swsh" ? "Start real Sword/Shield trade" : game === "za" ? "Start real Legends Z-A trade" : "Start real trade"}
        </button>
      </div>
      {status?.session && (
        <>
          <h3>USB session: {status.session.status}</h3>
          {sessionName && <p>Destination: {sessionName}</p>}
          <p role="status">{status.session.message}</p>
          <p>
            Link Code: <strong>{status.session.code}</strong>
          </p>
          {running && (
            <button
              disabled={busy}
              onClick={() =>
                perform(async () => {
                  await api(`/api/usb/${status.session!.id}/stop`, {
                    method: "POST",
                  });
                })
              }
            >
              Stop USB trade
            </button>
          )}
          {["interrupted", "uncertain", "recovery_required"].includes(
            status.session.status,
          ) && (
            <>
              <button
                disabled={busy}
                onClick={() =>
                  perform(async () => {
                    await api(`/api/usb/${status.session!.id}/recover`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        resolve_without_confirmation: false,
                      }),
                    });
                    onChange();
                  })
                }
              >
                Recover confirmed receipt
              </button>
              {status.session.status !== "recovery_required" && (
                <>
                  <label className="setting-row">
                    <span>
                      I stopped the old process and checked the game; resolve
                      this unconfirmed session while retaining all raw files and
                      Bank originals.
                    </span>
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => setChecked(e.target.checked)}
                    />
                  </label>
                  <button
                    disabled={busy || !checked}
                    onClick={() =>
                      perform(async () => {
                        await api(`/api/usb/${status.session!.id}/recover`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            resolve_without_confirmation: true,
                          }),
                        });
                      })
                    }
                  >
                    Resolve unconfirmed session
                  </button>
                </>
              )}
            </>
          )}
          {status.session.status === "completed" && (
            <a className="primary" href="#boxes" onClick={onChange}>
              View received Pokémon
            </a>
          )}
          <pre className="session-log" aria-label="USB session log">
            {status.logs.join("\n")}
          </pre>
        </>
      )}
    </section>
  );
}
