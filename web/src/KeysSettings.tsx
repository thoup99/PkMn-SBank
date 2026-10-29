import { useEffect, useRef, useState } from "react";
import { api } from "./BankTools";

export default function KeysSettings() {
  const fileInput = useRef<HTMLInputElement>(null);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/settings/keys").then(data => setInstalled(data.installed)).catch(err => setError(err.message));
  }, []);
  return <section className="panel settings">
    <h2>Switch keys</h2>
    <p className="muted">Upload your own prod.keys to the Pi for real Switch trades. This replaces previously installed keys. Key contents are never displayed or included in Bank backups. Use this upload only on your trusted local network.</p>
    <div className="keys-upload-controls">
      <button type="button" className="primary" disabled={busy}
        onClick={() => fileInput.current?.click()}>
        {busy ? "Installing keys…" : "Upload prod.keys"}
      </button>
      <span role="status" className={installed === null ? undefined : installed ? "keys-status-present" : "keys-status-missing"}>{installed === null ? "Checking keys…" : installed ? "Keys are present" : "Keys not uploaded"}</span>
    </div>
    <input ref={fileInput} type="file" hidden aria-label="prod.keys file" disabled={busy} onChange={async e => {
        const input = e.currentTarget, file = input.files?.[0];
        if (!file) return;
        setError(""); setBusy(true);
        try {
          if (file.size > 256 * 1024) throw new Error("The keys upload limit is 256 KiB.");
          const data = await api("/api/settings/keys", {method:"PUT", headers:{"Content-Type":"application/octet-stream"}, body:file});
          setInstalled(data.installed);
        } catch (err) { setError((err as Error).message); }
        finally { setBusy(false); input.value = ""; }
      }} />

    {error && <p role="alert">{error}</p>}
  </section>;
}
