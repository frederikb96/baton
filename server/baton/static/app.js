"use strict";

const $ = (id) => document.getElementById(id);
const POLL_MS = 3000;
const RENEW_WARNING_DAYS = 14;
let playback = null;
let authMode = "key";
let busy = false;

async function api(method, path, body) {
  const options = { method, credentials: "same-origin", headers: { "X-Baton-Request": "1" } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`/api/ui${path}`, options);
  let data = null;
  try {
    data = await response.json();
  } catch (_) {
    data = null;
  }
  if (response.status === 401) {
    showLogin();
  }
  return { ok: response.ok, status: response.status, data };
}

function detail(result) {
  const d = result.data && result.data.detail;
  if (d && typeof d === "object") return d.message || d.error;
  return d || `Request failed (${result.status})`;
}

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function fmt(ms) {
  const total = Math.max(0, Math.floor((ms || 0) / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

// views ---------------------------------------------------------------------------------

function showLogin() {
  $("login-view").hidden = false;
  $("app-view").hidden = true;
  $("logout").hidden = true;
  $("login-pill").hidden = true;
}

function showApp() {
  $("login-view").hidden = true;
  $("app-view").hidden = false;
  $("logout").hidden = authMode !== "key";
}

// player --------------------------------------------------------------------------------

function render(state) {
  playback = state
    ? { progress: state.progress_ms || 0, duration: state.duration_ms || 0,
        playing: state.is_playing, at: performance.now() }
    : null;
  $("np-title").textContent = state && state.title ? state.title : "Nothing playing";
  $("np-artist").textContent = state && state.artist ? state.artist : "";
  $("np-device").textContent = state && state.device_name ? `Playing on ${state.device_name}` : "No active device";
  $("btn-play").textContent = state && state.is_playing ? "⏸" : "▶";
  const hasTrack = Boolean(state && state.liked !== null);
  const like = $("btn-like");
  like.disabled = !hasTrack;
  like.textContent = state && state.liked ? "Liked (tap to unlike)" : "Like";
  like.classList.toggle("on", Boolean(state && state.liked));
  const pl = $("btn-playlist");
  const name = state && state.playlist_name;
  pl.disabled = !hasTrack || !name;
  pl.textContent = !name ? "No target playlist" : state.in_playlist ? `In ${name} (tap to remove)` : `Add to ${name}`;
  pl.classList.toggle("on", Boolean(state && state.in_playlist));
  tick();
}

function tick() {
  if (!playback) {
    $("np-bar").style.width = "0";
    $("np-pos").textContent = fmt(0);
    $("np-dur").textContent = fmt(0);
    return;
  }
  const elapsed = playback.playing ? performance.now() - playback.at : 0;
  const position = Math.min(playback.duration || Infinity, playback.progress + elapsed);
  $("np-pos").textContent = fmt(position);
  $("np-dur").textContent = fmt(playback.duration);
  $("np-bar").style.width = playback.duration ? `${Math.min(100, (position / playback.duration) * 100)}%` : "0";
}

function applyReply(result) {
  const reply = result.data;
  if (!reply || reply.result === undefined) {
    $("msg").textContent = detail(result);
    return;
  }
  if (reply.state) render(reply.state);
  if (reply.result === "already") $("msg").textContent = "Already done.";
  else if (reply.result === "error") $("msg").textContent = reply.message || reply.error;
  else $("msg").textContent = reply.message || "";
  if (reply.error === "spotify_auth") loadStatus();
}

async function command(path) {
  if (busy) return;
  busy = true;
  try {
    applyReply(await api("POST", path));
  } finally {
    busy = false;
  }
}

async function refreshState() {
  if (busy || document.hidden || $("app-view").hidden) return;
  const result = await api("GET", "/state");
  if (result.ok && result.data.state !== undefined && result.data.result === "ok") {
    render(result.data.state);
    if (!$("msg").textContent.startsWith("Already")) $("msg").textContent = "";
  } else if (result.data && result.data.error) {
    $("msg").textContent = result.data.message;
  }
}

// status, settings ----------------------------------------------------------------------

function select(node, items, selected, empty) {
  node.replaceChildren();
  if (empty !== undefined) node.append(new Option(empty, ""));
  for (const item of items) node.append(new Option(item.name, item.id, false, item.id === selected));
  if (selected && !items.some((i) => i.id === selected)) {
    node.append(new Option("(current, not listed)", selected, false, true));
  }
}

async function loadStatus() {
  const result = await api("GET", "/status");
  if (!result.ok) return null;
  authMode = result.data.auth_mode;
  showApp();
  const sp = result.data.spotify;
  const pill = $("login-pill");
  pill.hidden = false;
  pill.className = "pill";
  const banner = $("banner");
  banner.hidden = true;
  if (!sp.linked) {
    pill.textContent = "Spotify: not linked";
    pill.classList.add("bad");
    $("sp-status").textContent = "Not linked yet. Log in to control Spotify.";
  } else if (!sp.valid) {
    pill.textContent = "Spotify: login expired";
    pill.classList.add("bad");
    $("sp-status").textContent = sp.message || "Login expired.";
  } else {
    pill.textContent = `Spotify login: ${sp.expires_in_days} days left`;
    pill.classList.add(sp.expires_in_days <= RENEW_WARNING_DAYS ? "bad" : "ok");
    $("sp-status").textContent =
      `Logged in. Spotify logins last six months; renew in ${sp.expires_in_days} days.`;
  }
  if (!sp.linked || !sp.valid) {
    banner.textContent = $("sp-status").textContent;
    banner.hidden = false;
  }
  $("sp-login").textContent = sp.linked ? "Log in again" : "Log in with Spotify";
  $("sp-disconnect").hidden = !sp.linked;
  $("set-market").value = result.data.settings.market || "";
  return result.data;
}

async function loadPickers(settings) {
  const [playlists, devices] = await Promise.all([api("GET", "/spotify/playlists"), api("GET", "/spotify/devices")]);
  const target = settings.target_playlist ? settings.target_playlist.id : "";
  const device = settings.default_device ? settings.default_device.id : "";
  const playlistItems = playlists.ok ? playlists.data.playlists : [];
  const deviceItems = devices.ok ? devices.data.devices : [];
  const known = (ref, items) => (ref && !items.some((i) => i.id === ref.id) ? [ref] : []);
  select($("set-playlist"), [...playlistItems, ...known(settings.target_playlist, playlistItems)], target, "None");
  select($("set-device"), [...deviceItems, ...known(settings.default_device, deviceItems)], device, "None");
  const active = deviceItems.find((d) => d.is_active);
  select($("device-select"), deviceItems, active ? active.id : "");
}

async function saveSettings() {
  const body = {
    target_playlist_id: $("set-playlist").value || null,
    default_device_id: $("set-device").value || null,
    market: $("set-market").value.trim() || null,
  };
  const result = await api("PUT", "/settings", body);
  $("set-msg").textContent = result.ok ? "Saved." : detail(result);
  if (result.ok) await refreshState();
}

async function loadRecent() {
  const result = await api("GET", "/playlists/recent");
  const list = $("recent");
  list.replaceChildren();
  if (!result.ok || result.data.result !== "ok") {
    list.append(el("li", result.data && result.data.message ? result.data.message : "Not available.", "muted"));
    return;
  }
  if (result.data.playlists.length === 0) list.append(el("li", "Nothing played from a playlist recently.", "muted"));
  for (const playlist of result.data.playlists) {
    const item = el("li");
    item.append(el("span", playlist.name));
    for (const [mode, label] of [["normal", "Play"], ["shuffle", "Shuffle"], ["smart", "Smart"]]) {
      const button = el("button", label);
      button.addEventListener("click", async () => {
        applyReply(await api("POST", `/playlists/${encodeURIComponent(playlist.id)}/play?mode=${mode}`));
      });
      item.append(button);
    }
    list.append(item);
  }
}

// keys ----------------------------------------------------------------------------------

async function loadKeys() {
  const result = await api("GET", "/keys");
  const list = $("keys");
  list.replaceChildren();
  if (!result.ok) return;
  const keys = result.data.keys.filter((k) => !k.revoked);
  if (keys.length === 0) list.append(el("li", "No keys yet. Create one for the watch.", "muted"));
  for (const key of keys) {
    const used = key.last_used_at ? new Date(key.last_used_at * 1000).toLocaleString() : "never used";
    const item = el("li");
    item.append(el("span", `${key.name} (${key.hint}…), ${used}`));
    const revoke = el("button", "Revoke");
    revoke.addEventListener("click", async () => {
      if (!confirm(`Revoke the key "${key.name}"? Watches using it stop working.`)) return;
      await api("DELETE", `/keys/${key.id}`);
      await loadKeys();
    });
    item.append(revoke);
    list.append(item);
  }
}

async function createKey(event) {
  event.preventDefault();
  const result = await api("POST", "/keys", { name: $("key-name").value.trim() });
  if (!result.ok) return;
  $("key-value").textContent = result.data.key;
  $("key-new").hidden = false;
  $("key-name").value = "";
  await loadKeys();
}

// start ---------------------------------------------------------------------------------

async function login(event) {
  event.preventDefault();
  const result = await api("POST", "/login", { key: $("login-key").value });
  $("login-error").textContent = result.ok ? "" : detail(result);
  if (result.ok) {
    $("login-key").value = "";
    await start();
  }
}

async function start() {
  const session = await api("GET", "/session");
  if (!session.ok || !session.data.authenticated) {
    authMode = session.data ? session.data.auth_mode : "key";
    showLogin();
    return;
  }
  const status = await loadStatus();
  if (!status) return;
  await Promise.all([refreshState(), loadPickers(status.settings), loadRecent(), loadKeys()]);
}

$("login-form").addEventListener("submit", login);
$("logout").addEventListener("click", async () => {
  await api("POST", "/logout", {});
  showLogin();
});
$("btn-play").addEventListener("click", () => command("/play-pause"));
$("btn-next").addEventListener("click", () => command("/next"));
$("btn-prev").addEventListener("click", () => command("/previous"));
$("btn-like").addEventListener("click", () => command(playback && $("btn-like").classList.contains("on") ? "/unlike" : "/like"));
$("btn-playlist").addEventListener("click", () =>
  command($("btn-playlist").classList.contains("on") ? "/playlist/remove" : "/playlist/add"));
$("device-switch").addEventListener("click", async () => {
  const id = $("device-select").value;
  if (!id) return;
  applyReply(await api("POST", "/device", { device_id: id }));
});
$("set-save").addEventListener("click", saveSettings);
$("key-form").addEventListener("submit", createKey);
$("sp-disconnect").addEventListener("click", async () => {
  if (!confirm("Forget the Spotify login?")) return;
  await api("POST", "/spotify/disconnect", {});
  await start();
});
document.addEventListener("visibilitychange", refreshState);
setInterval(refreshState, POLL_MS);
setInterval(tick, 500);
start();
