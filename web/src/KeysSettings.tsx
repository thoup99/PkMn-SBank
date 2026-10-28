import { useEffect, useState } from "react";
import { api } from "./BankTools";

export default function KeysSettings() {
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    api("/api/settings/keys").then(data => setInstalled(data.installed)).catch(err => setError(err.message));
  }, []);
  return <section className="panel settings">
    <h2>Switch keys</h2>
    <p className="muted">Upload your own prod.keys to the Pi for real Switch trades. This replaces previously installed keys. Key contents are never displayed or included in Bank backups. Use this upload only on your trusted local network.</p>
    <p role="status">{installed === null ? "Checking keys…" : installed ? "Keys installed on the Pi" : "No readable keys installed"}</p>
    <label>prod.keys file
      <input type="file" disabled={busy} onChange={async e => {
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
    </label>
    {busy && <p>Installing keys…</p>}
    {error && <p role="alert">{error}</p>}
  </section>;
}
