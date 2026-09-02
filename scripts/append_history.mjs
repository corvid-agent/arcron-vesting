#!/usr/bin/env node
/**
 * Append a LocalNet listen.json sample onto docs/history.json.
 * Never writes docs/deploy.json. Never invents TestNet ids.
 * Usage: node scripts/append_history.mjs
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const listenPath = join(root, "docs", "listen.json");
const historyPath = join(root, "docs", "history.json");
const deployPath = join(root, "docs", "deploy.json");

function die(msg) {
  console.error(msg);
  process.exit(1);
}

if (!existsSync(listenPath)) die("missing docs/listen.json");
const listen = JSON.parse(readFileSync(listenPath, "utf8"));
if (listen.network !== "localnet") die("refusing: listen.json is not localnet");
const appId = Number(listen.appId || 0);
if (!(appId > 0)) die("refusing: listen.json appId missing");
if (String(listen.genesisId || "").toLowerCase().includes("testnet")) {
  die("refusing: genesis looks like TestNet");
}

const g = listen.global || {};
const locked = Number(g.locked || 0);
const claimed = Number(g.claimed || 0);
const sample = {
  t: listen.listened_at || new Date().toISOString(),
  network: "localnet",
  genesisId: listen.genesisId || "dockernet-v1",
  appId,
  mockKeeperAppId: Number(listen.mockKeeperAppId || 0),
  lastRound: Number(listen.lastRound || 0),
  locked,
  credited: Number(g.credited || 0),
  claimed,
  last_accrue_round: Number(g.last_accrue_round || 0),
  remaining: Math.max(0, locked - claimed),
  calls: Array.isArray(listen.calls) ? listen.calls.length : 0,
  source: "docs/listen.json",
};

let history = [];
if (existsSync(historyPath)) {
  history = JSON.parse(readFileSync(historyPath, "utf8"));
}
if (!Array.isArray(history)) history = [];

const dup = history.some(
  (r) =>
    Number(r.appId) === sample.appId &&
    Number(r.lastRound) === sample.lastRound &&
    String(r.t) === String(sample.t)
);
if (!dup) history.push(sample);

// Honesty: never copy LocalNet app ids into deploy.json
const deploy = JSON.parse(readFileSync(deployPath, "utf8"));
if (Number(deploy.appId || 0) !== 0) {
  console.warn("warn: deploy.json appId is non-zero; this script does not modify it");
}
if (String(deploy.appId) === String(sample.appId)) {
  die("refusing: LocalNet appId already equals deploy.json appId");
}

writeFileSync(historyPath, JSON.stringify(history, null, 2) + "\n");
console.log(
  JSON.stringify({
    appended: !dup,
    samples: history.length,
    appId: sample.appId,
    path: historyPath,
    notes: "LocalNet history only. deploy.json untouched.",
  })
);
