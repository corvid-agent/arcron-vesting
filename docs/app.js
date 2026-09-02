const INDEXER = "https://testnet-idx.algonode.cloud";
const KEEPER = 769891898;
const PHOS = "#7cff6b";
const DIM = "#3a8a32";
const AMBER = "#e6c15a";
const DEAD = "#143318";

function flaps(el, text, width) {
  const s = String(text).padStart(width, " ").slice(-width);
  el.replaceChildren();
  for (const ch of s) {
    const d = document.createElement("span");
    d.className = "flap" + (ch === " " ? " blank" : "");
    d.textContent = ch === " " ? "0" : ch;
    el.appendChild(d);
  }
}

function paint(status, cls, title) {
  const headline = document.getElementById("headline");
  headline.textContent = status;
  headline.className = "destination " + cls;
  document.title = title;
}

function b64utf8(b64) {
  try { return atob(b64); } catch { return ""; }
}

function b64bytes(b64) {
  try {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  } catch {
    return new Uint8Array(0);
  }
}

function readGlobal(state, name) {
  if (!Array.isArray(state)) return null;
  for (const kv of state) {
    if (b64utf8(kv.key) !== name) continue;
    if (kv.value && kv.value.type === 2) return kv.value.uint;
    if (kv.value && kv.value.type === 1) return kv.value.bytes;
    return null;
  }
  return null;
}

const MASK64 = 0xffffffffffffffffn;
const rotr64 = (x, n) => ((x >> BigInt(n)) | (x << BigInt(64 - n))) & MASK64;
const shr64 = (x, n) => (x >> BigInt(n)) & MASK64;

const SHA512_K = [
  0x428a2f98d728ae22n, 0x7137449123ef65cdn, 0xb5c0fbcfec4d3b2fn, 0xe9b5dba58189dbbcn,
  0x3956c25bf348b538n, 0x59f111f1b605d019n, 0x923f82a4af194f9bn, 0xab1c5ed5da6d8118n,
  0xd807aa98a3030242n, 0x12835b0145706fben, 0x243185be4ee4b28cn, 0x550c7dc3d5ffb4e2n,
  0x72be5d74f27b896fn, 0x80deb1fe3b1696b1n, 0x9bdc06a725c71235n, 0xc19bf174cf692694n,
  0xe49b69c19ef14ad2n, 0xefbe4786384f25e3n, 0x0fc19dc68b8cd5b5n, 0x240ca1cc77ac9c65n,
  0x2de92c6f592b0275n, 0x4a7484aa6ea6e483n, 0x5cb0a9dcbd41fbd4n, 0x76f988da831153b5n,
  0x983e5152ee66dfabn, 0xa831c66d2db43210n, 0xb00327c898fb213fn, 0xbf597fc7beef0ee4n,
  0xc6e00bf33da88fc2n, 0xd5a79147930aa725n, 0x06ca6351e003826fn, 0x142929670a0e6e70n,
  0x27b70a8546d22ffcn, 0x2e1b21385c26c926n, 0x4d2c6dfc5ac42aedn, 0x53380d139d95b3dfn,
  0x650a73548baf63den, 0x766a0abb3c77b2a8n, 0x81c2c92e47edaee6n, 0x92722c851482353bn,
  0xa2bfe8a14cf10364n, 0xa81a664bbc423001n, 0xc24b8b70d0f89791n, 0xc76c51a30654be30n,
  0xd192e819d6ef5218n, 0xd69906245565a910n, 0xf40e35855771202an, 0x106aa07032bbd1b8n,
  0x19a4c116b8d2d0c8n, 0x1e376c085141ab53n, 0x2748774cdf8eeb99n, 0x34b0bcb5e19b48a8n,
  0x391c0cb3c5c95a63n, 0x4ed8aa4ae3418acbn, 0x5b9cca4f7763e373n, 0x682e6ff3d6b2b8a3n,
  0x748f82ee5defb2fcn, 0x78a5636f43172f60n, 0x84c87814a1f0ab72n, 0x8cc702081a6439ecn,
  0x90befffa23631e28n, 0xa4506cebde82bde9n, 0xbef9a3f7b2c67915n, 0xc67178f2e372532bn,
  0xca273eceea26619cn, 0xd186b8c721c0c207n, 0xeada7dd6cde0eb1en, 0xf57d4f7fee6ed178n,
  0x06f067aa72176fban, 0x0a637dc5a2c898a6n, 0x113f9804bef90daen, 0x1b710b35131c471bn,
  0x28db77f523047d84n, 0x32caab7b40c72493n, 0x3c9ebe0a15c9bebcn, 0x431d67c49c100d4cn,
  0x4cc5d4becb3e42b6n, 0x597f299cfc657e2an, 0x5fcb6fab3ad6faecn, 0x6c44198c4a475817n,
];

function sha512_256(bytes) {
  const H = [
    0x22312194fc2bf72cn, 0x9f555fa3c84c64c2n, 0x2393b86b6f53b151n, 0x963877195940eabdn,
    0x96283ee2a88effe3n, 0xbe5e1e2553863992n, 0x2b0199fc2c85b8aan, 0x0eb72ddc81c52ca2n,
  ];
  const ml = bytes.length;
  const paddedLen = Math.ceil((ml + 17) / 128) * 128;
  const buf = new Uint8Array(paddedLen);
  buf.set(bytes);
  buf[ml] = 0x80;
  const bitLen = BigInt(ml) * 8n;
  for (let i = 0; i < 16; i++) {
    buf[paddedLen - 1 - i] = Number((bitLen >> BigInt(8 * i)) & 0xffn);
  }
  for (let off = 0; off < paddedLen; off += 128) {
    const W = new Array(80);
    for (let i = 0; i < 16; i++) {
      let v = 0n;
      for (let j = 0; j < 8; j++) v = (v << 8n) | BigInt(buf[off + i * 8 + j]);
      W[i] = v;
    }
    for (let i = 16; i < 80; i++) {
      const s0 = rotr64(W[i - 15], 1) ^ rotr64(W[i - 15], 8) ^ shr64(W[i - 15], 7);
      const s1 = rotr64(W[i - 2], 19) ^ rotr64(W[i - 2], 61) ^ shr64(W[i - 2], 6);
      W[i] = (W[i - 16] + s0 + W[i - 7] + s1) & MASK64;
    }
    let a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], h = H[7];
    for (let i = 0; i < 80; i++) {
      const S1 = rotr64(e, 14) ^ rotr64(e, 18) ^ rotr64(e, 41);
      const ch = (e & f) ^ (((~e) & MASK64) & g);
      const t1 = (h + S1 + ch + SHA512_K[i] + W[i]) & MASK64;
      const S0 = rotr64(a, 28) ^ rotr64(a, 34) ^ rotr64(a, 39);
      const maj = (a & b) ^ (a & c) ^ (b & c);
      const t2 = (S0 + maj) & MASK64;
      h = g; g = f; f = e; e = (d + t1) & MASK64;
      d = c; c = b; b = a; a = (t1 + t2) & MASK64;
    }
    H[0] = (H[0] + a) & MASK64;
    H[1] = (H[1] + b) & MASK64;
    H[2] = (H[2] + c) & MASK64;
    H[3] = (H[3] + d) & MASK64;
    H[4] = (H[4] + e) & MASK64;
    H[5] = (H[5] + f) & MASK64;
    H[6] = (H[6] + g) & MASK64;
    H[7] = (H[7] + h) & MASK64;
  }
  const out = new Uint8Array(32);
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 8; j++) {
      out[i * 8 + j] = Number((H[i] >> BigInt(56 - 8 * j)) & 0xffn);
    }
  }
  return out;
}

const B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function encodeAddress(pk) {
  if (!(pk instanceof Uint8Array) || pk.length !== 32) return "—";
  let z = true;
  for (let i = 0; i < 32; i++) if (pk[i] !== 0) { z = false; break; }
  if (z) return "—";
  const checksum = sha512_256(pk).slice(28, 32);
  const buf = new Uint8Array(36);
  buf.set(pk, 0);
  buf.set(checksum, 32);
  let bits = 0n;
  let nbits = 0;
  let out = "";
  for (let i = 0; i < buf.length; i++) {
    bits = (bits << 8n) | BigInt(buf[i]);
    nbits += 8;
    while (nbits >= 5) {
      nbits -= 5;
      out += B32[Number((bits >> BigInt(nbits)) & 31n)];
    }
  }
  if (nbits > 0) out += B32[Number((bits << BigInt(5 - nbits)) & 31n)];
  return out.slice(0, 58);
}

async function loadConfig() {
  const res = await fetch("./deploy.json", { cache: "no-store" });
  if (!res.ok) throw new Error("deploy.json " + res.status);
  return res.json();
}

function sizeCanvas(c) {
  const dpr = window.devicePixelRatio || 1;
  const rect = c.getBoundingClientRect();
  const w = Math.max(280, Math.floor(rect.width || c.width || 640));
  const h = Math.max(100, Math.floor((c.height / (c.width || 640)) * w));
  c.width = Math.floor(w * dpr);
  c.height = Math.floor(h * dpr);
  const ctx = c.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, w, h };
}

function drawEscrowBars(locked, credited, claimed) {
  const c = document.getElementById("escrow-canvas");
  if (!c) return;
  const { ctx, w, h } = sizeCanvas(c);
  ctx.clearRect(0, 0, w, h);
  const vals = [
    { label: "locked", v: Number(locked || 0), color: PHOS },
    { label: "credited", v: Number(credited || 0), color: AMBER },
    { label: "claimed", v: Number(claimed || 0), color: DIM },
  ];
  const max = Math.max(...vals.map((x) => x.v), 1);
  const barH = Math.min(28, (h - 36) / vals.length - 8);
  vals.forEach((row, i) => {
    const y = 18 + i * (barH + 14);
    const bw = Math.max(2, (row.v / max) * (w - 110));
    ctx.fillStyle = DEAD;
    ctx.fillRect(90, y, w - 110, barH);
    ctx.fillStyle = row.color;
    ctx.shadowColor = row.color;
    ctx.shadowBlur = 8;
    ctx.fillRect(90, y, bw, barH);
    ctx.shadowBlur = 0;
    ctx.fillStyle = DIM;
    ctx.font = "11px IBM Plex Mono, monospace";
    ctx.fillText(row.label, 4, y + barH - 6);
    ctx.fillStyle = PHOS;
    ctx.fillText(String(row.v), 94, y + barH - 6);
  });
}

function drawHistoryLine(rows) {
  const c = document.getElementById("history-canvas");
  const meta = document.getElementById("history-meta");
  if (!c) return;
  const { ctx, w, h } = sizeCanvas(c);
  ctx.clearRect(0, 0, w, h);
  if (meta) meta.textContent = "sqlite " + rows.length + " samples · LocalNet only";
  if (!rows.length) {
    ctx.fillStyle = DIM;
    ctx.font = "12px IBM Plex Mono, monospace";
    ctx.fillText("no history yet", 12, 28);
    return;
  }
  const locked = rows.map((r) => Number(r.locked || 0));
  const remaining = rows.map((r) => Number(r.remaining != null ? r.remaining : Math.max(0, (r.locked || 0) - (r.claimed || 0))));
  const credited = rows.map((r) => Number(r.credited || 0));
  const max = Math.max(...locked, ...credited, ...remaining, 1);
  const pad = 16;
  function series(vals, color, fill) {
    ctx.beginPath();
    vals.forEach((v, i) => {
      const px = pad + (i * (w - pad * 2)) / Math.max(1, vals.length - 1);
      const py = h - pad - (v / max) * (h - pad * 2);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.shadowColor = color;
    ctx.shadowBlur = 6;
    ctx.stroke();
    ctx.shadowBlur = 0;
    if (fill) {
      const lastX = pad + ((vals.length - 1) * (w - pad * 2)) / Math.max(1, vals.length - 1);
      ctx.lineTo(lastX, h - pad);
      ctx.lineTo(pad, h - pad);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
    }
  }
  series(locked, PHOS, "rgba(124,255,107,0.08)");
  series(credited, AMBER, null);
  series(remaining, DIM, null);
  // mark app ids under points
  ctx.fillStyle = DIM;
  ctx.font = "10px IBM Plex Mono, monospace";
  rows.forEach((r, i) => {
    const px = pad + (i * (w - pad * 2)) / Math.max(1, rows.length - 1);
    ctx.fillText(String(r.appId || ""), px - 10, h - 2);
  });
}

function drawTimeline(calls) {
  const c = document.getElementById("timeline-canvas");
  if (!c) return;
  const { ctx, w, h } = sizeCanvas(c);
  ctx.clearRect(0, 0, w, h);
  const steps = Array.isArray(calls) && calls.length
    ? calls.map((x) => ({ method: x.method || "?", round: x.round, ok: !!x.success }))
    : [
        { method: "set_keeper", ok: false },
        { method: "configure", ok: false },
        { method: "fund", ok: false },
        { method: "accrue", ok: false },
        { method: "claim", ok: false },
      ];
  const n = steps.length;
  const y = h / 2;
  ctx.strokeStyle = DEAD;
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(24, y);
  ctx.lineTo(w - 24, y);
  ctx.stroke();
  steps.forEach((s, i) => {
    const px = 24 + (i * (w - 48)) / Math.max(1, n - 1);
    ctx.beginPath();
    ctx.arc(px, y, s.ok ? 7 : 5, 0, Math.PI * 2);
    ctx.fillStyle = s.ok ? PHOS : DEAD;
    ctx.shadowColor = s.ok ? PHOS : "transparent";
    ctx.shadowBlur = s.ok ? 10 : 0;
    ctx.fill();
    ctx.shadowBlur = 0;
    ctx.fillStyle = s.ok ? PHOS : DIM;
    ctx.font = "10px IBM Plex Mono, monospace";
    ctx.textAlign = "center";
    ctx.fillText(s.method, px, y - 14);
    if (s.round != null) ctx.fillText("r" + s.round, px, y + 22);
  });
  ctx.textAlign = "left";
}

let sqlDb = null;

async function bootSql(rows) {
  if (typeof initSqlJs !== "function") return rows;
  const SQL = await initSqlJs({
    locateFile: (f) => "https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.11.0/" + f,
  });
  sqlDb = new SQL.Database();
  sqlDb.run(
    "CREATE TABLE samples (t TEXT, network TEXT, appId INTEGER, mockKeeperAppId INTEGER, lastRound INTEGER, locked INTEGER, credited INTEGER, claimed INTEGER, remaining INTEGER, last_accrue_round INTEGER, calls INTEGER, source TEXT);"
  );
  const ins = sqlDb.prepare(
    "INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?)"
  );
  rows.forEach((r) => {
    const locked = Number(r.locked || 0);
    const claimed = Number(r.claimed || 0);
    const remaining = r.remaining != null ? Number(r.remaining) : Math.max(0, locked - claimed);
    ins.run([
      r.t || "",
      r.network || "localnet",
      Number(r.appId || 0),
      Number(r.mockKeeperAppId || 0),
      Number(r.lastRound || 0),
      locked,
      Number(r.credited || 0),
      claimed,
      remaining,
      Number(r.last_accrue_round || 0),
      Number(r.calls || 0),
      r.source || "",
    ]);
  });
  ins.free();
  const res = sqlDb.exec(
    "SELECT t, network, appId, mockKeeperAppId, lastRound, locked, credited, claimed, remaining, last_accrue_round, calls, source FROM samples WHERE network='localnet' ORDER BY lastRound, appId"
  );
  if (!res[0]) return rows;
  return res[0].values.map((v) => ({
    t: v[0],
    network: v[1],
    appId: v[2],
    mockKeeperAppId: v[3],
    lastRound: v[4],
    locked: v[5],
    credited: v[6],
    claimed: v[7],
    remaining: v[8],
    last_accrue_round: v[9],
    calls: v[10],
    source: v[11],
  }));
}

async function loadHistoryGraphs(listen) {
  let history = [];
  try {
    const res = await fetch("./history.json", { cache: "no-store" });
    if (res.ok) history = await res.json();
  } catch (_) {
    history = [];
  }
  if (!Array.isArray(history)) history = [];
  // Only LocalNet rows — never paint TestNet-looking ids from history.
  history = history.filter((r) => r && r.network === "localnet" && Number(r.appId) > 0);
  let rows = history;
  try {
    rows = await bootSql(history);
  } catch (_) {
    rows = history;
  }
  const g = (listen && listen.global) || {};
  const locked = Number(g.locked != null ? g.locked : (rows[rows.length - 1] && rows[rows.length - 1].locked) || 0);
  const credited = Number(g.credited != null ? g.credited : (rows[rows.length - 1] && rows[rows.length - 1].credited) || 0);
  const claimed = Number(g.claimed != null ? g.claimed : (rows[rows.length - 1] && rows[rows.length - 1].claimed) || 0);
  drawEscrowBars(locked, credited, claimed);
  drawHistoryLine(rows);
  drawTimeline(listen && Array.isArray(listen.calls) ? listen.calls : []);
}

async function loadLocalnetProof() {
  const el = document.getElementById("localnet-proof");
  if (!el) return null;
  let listen = null;
  try {
    const res = await fetch("./localnet.json", { cache: "no-store" });
    if (!res.ok) {
      await loadHistoryGraphs(null);
      return null;
    }
    const ln = await res.json();
    if (!ln || ln.network !== "localnet" || !(Number(ln.appId) > 0)) {
      await loadHistoryGraphs(null);
      return null;
    }
    el.hidden = false;
    let line =
      "LocalNet proof · app " + ln.appId +
      " · round " + (ln.confirmedRound != null ? ln.confirmedRound : "—") +
      " · " + (ln.genesisId || "dockernet") +
      " · not TestNet (see docs/localnet.json)";
    try {
      const lr = await fetch("./listen.json", { cache: "no-store" });
      if (lr.ok) {
        listen = await lr.json();
        if (listen && listen.network === "localnet" && Number(listen.appId) === Number(ln.appId)) {
          const g = listen.global || {};
          const when = listen.listened_at
            ? " · heard " + String(listen.listened_at).replace(/\.\d+/, "").replace("Z", "Z")
            : "";
          const locked = Number(g.locked || 0);
          const claimed = Number(g.claimed || 0);
          const remaining = Math.max(0, locked - claimed);
          flaps(document.getElementById("accrue"), String(g.last_accrue_round || 0), 10);
          flaps(document.getElementById("remaining"), String(remaining), 12);
          if (listen.mockKeeperAppId) {
            flaps(document.getElementById("keeper"), String(listen.mockKeeperAppId), 10);
          }
          const calls = Array.isArray(listen.calls) ? listen.calls : [];
          const cfgCall = calls.find((c) => c && c.method === "configure" && c.beneficiary);
          if (cfgCall && cfgCall.beneficiary) {
            document.getElementById("beneficiary").textContent = cfgCall.beneficiary;
          }
          line +=
            " · mock keeper " + (listen.mockKeeperAppId || "—") +
            " · accrue round " + (g.last_accrue_round || "—") +
            " · claimed " + claimed +
            " · remaining " + remaining +
            when +
            " (see docs/listen.json)";
        }
      }
    } catch (_) {
      /* optional listen.json */
    }
    el.textContent = line;
    await loadHistoryGraphs(listen);
    return listen;
  } catch (_) {
    await loadHistoryGraphs(null);
    return null;
  }
}

async function main() {
  flaps(document.getElementById("accrue"), "0", 10);
  flaps(document.getElementById("remaining"), "0", 12);
  flaps(document.getElementById("keeper"), String(KEEPER), 10);
  document.getElementById("beneficiary").textContent = "—";
  drawEscrowBars(0, 0, 0);
  drawHistoryLine([]);
  drawTimeline([]);

  let cfg;
  try {
    cfg = await loadConfig();
  } catch (e) {
    document.getElementById("err").hidden = false;
    document.getElementById("err").textContent = "Could not read deploy.json";
    await loadHistoryGraphs(null);
    return;
  }

  const appId = Number(cfg.appId) || 0;
  const keeper = Number(cfg.keeperAppId) || KEEPER;
  const subhead = document.getElementById("subhead");
  flaps(document.getElementById("keeper"), String(keeper), 10);

  if (appId <= 0) {
    paint("NOT DEPLOYED", "grounded", "VESTING — NOT DEPLOYED");
    subhead.textContent = "not deployed · keeper " + keeper;
    await loadLocalnetProof();
    return;
  }

  subhead.textContent = "app " + appId + " · upkeep " + (cfg.upkeepId || "—") + " · " + (cfg.network || "testnet");
  try {
    const res = await fetch(INDEXER + "/v2/applications/" + appId);
    if (!res.ok) throw new Error("indexer " + res.status);
    const body = await res.json();
    const g = (body.params && body.params["global-state"]) || [];
    const locked = readGlobal(g, "locked");
    const credited = readGlobal(g, "credited");
    const claimed = readGlobal(g, "claimed");
    const last = readGlobal(g, "last_accrue_round");
    const benB64 = readGlobal(g, "beneficiary");
    const remaining = Math.max(0, Number(locked || 0) - Number(claimed || 0));
    flaps(document.getElementById("accrue"), last == null ? "—" : String(last), 10);
    flaps(document.getElementById("remaining"), String(remaining), 12);
    flaps(document.getElementById("keeper"), String(keeper), 10);
    if (typeof benB64 === "string" && benB64) {
      document.getElementById("beneficiary").textContent = encodeAddress(b64bytes(benB64));
    }
    drawEscrowBars(locked || 0, credited || 0, claimed || 0);
    drawTimeline([]);
    await loadHistoryGraphs(null);
    if (!credited) {
      paint("WAITING FOR FIRST ACCRUE", "grounded", "VESTING — waiting for first accrue");
    } else {
      paint("LIVE", "live", "VESTING — remaining " + remaining);
    }
  } catch (e) {
    paint("GROUNDED", "grounded", "VESTING — GROUNDED");
    document.getElementById("err").hidden = false;
    document.getElementById("err").textContent = "Indexer unreachable; appId is set but state was not read.";
    await loadHistoryGraphs(null);
  }
}

main();
window.addEventListener("resize", () => {
  /* redrawn on next load; keep light */
});
