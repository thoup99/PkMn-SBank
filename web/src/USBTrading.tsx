import { useEffect, useState } from "react";
import { api } from "./BankTools";
import type { Box } from "./types";
interface USBSession {
  id: string;
  status: string;
  message: string;
  code: string;
  species: string;
  received_id: string | null;
}
interface USBStatus {
  supported_host: boolean;
  keys_available: boolean;
  devices: { device: string; description: string }[];
  session: USBSession | null;
  logs: string[];
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
    [device, setDevice] = useState(""),
    [code, setCode] = useState("12345678"),
    [entry, setEntry] = useState("dummy-pikachu-01");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [checked, setChecked] = useState(false);
  const refresh = async () => {
    const result = await api("/api/usb/status");
    setStatus(result);
    setDevice((current) => current || result.devices[0]?.device || "");
    return result;
  };
  useEffect(() => {
    refresh().catch((err) => setError(err.message));
  }, []);
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
  return (
    <section className="panel session-panel">
      <p className="eyebrow">PHASE 5 · REAL USB TRADE · SWORD / SHIELD</p>
      <h2>Trade with your Switch</h2>
      <p className="muted">
        This starts one real Link Trade using the ESP32-S3 on your Pi’s native
        USB serial port. A reserve Pikachu is prepared automatically. The
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
          Install your own Switch prod.keys on the Pi using the hardware guide.
          Keys are never uploaded in this page.
        </p>
      )}
      <label className="trade-field">
        Outgoing Pokémon
        <select
          value={entry}
          disabled={busy || blocked}
          onChange={(e) => setEntry(e.target.value)}
        >
          {boxes
            .flatMap((b) => b.slots)
            .filter((p) => p !== null)
            .map((p) => (
              <option value={p.id} key={p.id}>
                {p.species} ·{" "}
                {p.dummy ? "Reserve Pikachu (replenished)" : p.game} ·{" "}
                {p.id.slice(-8)}
              </option>
            ))}
        </select>
      </label>
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
            !device ||
            !/^\d{8}$/.test(code)
          }
          onClick={() =>
            perform(async () => {
              await api("/api/usb/start", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  entry_id: entry,
                  device,
                  code,
                  request_id: newRequestId(),
                }),
              });
              setChecked(false);
            })
          }
        >
          Start real Sword/Shield trade
        </button>
      </div>
      {status?.session && (
        <>
          <h3>USB session: {status.session.status}</h3>
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
