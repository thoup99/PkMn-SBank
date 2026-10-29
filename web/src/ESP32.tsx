import { useEffect, useState } from "react";
import { api } from "./BankTools";
import { newRequestId } from "./USBTrading";

type Job = {id: string; status: string; message: string; logs: string[]; release: string};
type Status = {
  supported_host: boolean; esptool_available: boolean; release: string | null;
  image: string | null; devices: {device: string; description: string}[]; job: Job | null;
};
const active = (job: Job | null) => !!job && ["starting", "running"].includes(job.status);

export default function ESP32({demo}: {demo: boolean}) {
  const [status, setStatus] = useState<Status | null>(null);
  const [device, setDevice] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const refresh = async () => {
    const value: Status = await api("/api/esp32/status");
    setStatus(value);
    setDevice(current => value.devices.some(d => d.device === current) ? current : value.devices[0]?.device || "");
  };
  useEffect(() => {refresh().catch(err => setError(err.message));}, []);
  useEffect(() => {
    if (!status || !active(status.job)) return;
    let mounted = true;
    const timer = window.setInterval(() => {
      api("/api/esp32/status").then(value => {if (mounted) setStatus(value);})
        .catch(err => {if (mounted) setError(err.message);});
    }, 1500);
    return () => {mounted = false; window.clearInterval(timer);};
  }, [status?.job?.status]);
  const running = active(status?.job || null);
  return <>
    <section className="panel settings">
      <h2>ESP32-S3 wireless firmware</h2>
      <p>Install the matching wireless radio firmware on the ESP32-S3 connected to your Raspberry Pi 5. This is the firmware used for Switch trades.</p>
      {demo && <p className="filter-message">Demo mode is read-only. Open the Pi’s normal Bank website to install firmware.</p>}
      {!demo && status && !status.supported_host && <p className="filter-message">Firmware installation requires the Raspberry Pi 5 server.</p>}
      {status && !status.esptool_available && !demo && <p className="filter-message">Run <code>bash scripts/setup_web_pi5.sh</code> on the Pi, then restart the website to install the flashing tools.</p>}
      <p>Matching release: <strong>{status?.release || "Not available"}</strong>{status?.image && <> · <code>{status.image}</code></>}</p>
      <label className="trade-field">Connected native USB board
        <select value={device} disabled={busy || running || demo} onChange={e => {setDevice(e.target.value); setConfirmed(false);}}>
          <option value="">Select a connected ESP32-S3</option>
          {status?.devices.map(d => <option key={d.device} value={d.device}>{d.device} · {d.description}</option>)}
        </select>
      </label>
      <p className="muted">S3, C3 and C6 share native USB identifiers. Verify your board is an ESP32-S3; the installer also checks the chip before writing. A listed port alone does not confirm working radio firmware.</p>
      <label className="setting-row">
        <span>I confirm this replaces the selected board’s existing firmware. I will keep it connected until installation finishes.</span>
        <input type="checkbox" checked={confirmed} disabled={busy || running || demo} onChange={e => setConfirmed(e.target.checked)}/>
      </label>
      <div className="trade-actions">
        <button disabled={busy} onClick={async () => {setError(""); try {await refresh();} catch (err) {setError((err as Error).message);}}}>Refresh boards and status</button>
        <button className="primary" disabled={demo || busy || running || !confirmed || !device || !status?.supported_host || !status.esptool_available}
          onClick={async () => {
            setBusy(true); setError("");
            try {
              const job = await api("/api/esp32/flash", {method:"POST", headers:{"Content-Type":"application/json"},
                body:JSON.stringify({device, confirmed:true, request_id:newRequestId()})});
              setStatus(current => current ? {...current, job} : current); setConfirmed(false);
            } catch (err) {
              setError((err as Error).message);
              try {await refresh();} catch {}
            } finally {setBusy(false);}
          }}>Install matching firmware</button>
      </div>
      {error && <p role="alert">{error}</p>}
      {status?.job && <>
        <h3>Installation: {status.job.status}</h3>
        <p role="status">{status.job.message}</p>
        <pre className="session-log" aria-label="Firmware installation log">{status.job.logs.join("\n")}</pre>
      </>}
    </section>
    <section className="panel settings">
      <h2>Connect and prepare your board</h2>
      <ol>
        <li>Connect the ESP32-S3 to the Pi using a USB data cable and its native USB/OTG socket, rather than a separate UART socket. Attach the antenna if your board requires one.</li>
        <li>Stop any trade, serial monitor or other application using the board. Recover or resolve any unfinished trade before flashing.</li>
        <li>Refresh boards, select the port, acknowledge firmware replacement and choose <strong>Install matching firmware</strong>. The Pi needs Internet access to download the matching release and its checksum. No Switch keys are needed for flashing.</li>
        <li>If the log stays at Connecting, hold <strong>BOOT</strong>, tap and release <strong>RESET/EN</strong>, then release BOOT. If the attempt fails, enter BOOT mode before retrying and refresh the port list because its name may change.</li>
        <li>Keep power and USB connected during writing. After completion, reset or reconnect the board normally, then open <a href="#trading">Trading</a> to test the radio connection.</li>
      </ol>
      <h3>Serial permissions on the Pi</h3>
      <p>If you see Permission denied, run this on the Pi, then log out and back in:</p>
      <pre className="session-log">sudo usermod -aG dialout "$USER"</pre>
      <p>Do not run the website as root. If no port appears, check the native socket and data cable. Boards running controller firmware may require manual BOOT mode to expose a serial port.</p>
      <h3>If installation is interrupted</h3>
      <p>Do not restart the website during installation. A server restart does not automatically retry flashing. The child installer keeps the USB lock until it exits, with a ten-minute deadline. Wait for any active write to finish before disconnecting. Inspect the result and retry only when necessary. A successful flash does not yet confirm a working Switch trade.</p>
    </section>
  </>;
}
