"use strict";

// Read-only view of the spool station. Wording and colours follow the touch UI (ui/src/format.cpp,
// view_model.cpp, widgets/printer_card.cpp); the data is the IPC protocol's snapshot and events.
(() => {
  const state = {
    service: null, scale: {}, scan: {}, spool: null, printers: [], health: {}, activity: [], settings: {},
  };
  let online = false;
  let connectedOnce = false;
  let retryMs = 1000;
  const dirty = new Set();
  let frame = 0;

  const byId = (id) => document.getElementById(id);

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  // ---- formatting -------------------------------------------------------------------------

  function num(value, decimals = 0) {
    const text = Number(value).toFixed(decimals);
    return /^-0(\.0+)?$/.test(text) ? text.slice(1) : text;
  }
  const grams = (value) => (value === null || value === undefined ? "--" : `${num(value)} g`);
  const delta = (value) => `${Math.round(value) < 0 ? "-" : "+"}${Math.abs(Math.round(value))} g`;
  const clamp = (value) => Math.min(100, Math.max(0, value));

  function percent(value) {
    return value > 0 && value < 1 ? "<1%" : `${Math.round(clamp(value))}%`;
  }

  function compactWeight(value) {
    const rounded = Math.round(Math.max(0, value));
    if (rounded < 1000) return [String(rounded), "g"];
    const kg = rounded / 1000;
    return [num(kg, kg >= 9.95 ? 0 : 1), "kg"];
  }

  const capitalize = (text) => (text ? text[0].toUpperCase() + text.slice(1) : text);
  const SCALE_LABELS = {
    stable: "Ready", zero: "Empty", motion: "Settling", under: "Re-zero", rezero: "Re-zero", over: "Overload",
    fault: "Error", calibrate: "Error",
  };
  const ACTIONS = {
    weigh: "Weigh", weigh_load: "Weigh + Load", load: "Load", scan: "Scan", assign_lane: "Assign lane",
    empty_spool: "Empty spool", clear_pending: "Clear pending", undo: "Undo", lookup: "Look up",
    spool_loaded: "Loaded", sleep: "Sleep", printer: "Printer",
  };
  const actionLabel = (action) => ACTIONS[action] || capitalize(String(action || "").replace(/_/g, " "));
  const printerLabel = (printer) => printer.display_name || printer.name;
  const isBambu = (printer) => printer.kind === "bambuddy";

  function printLabel(printState, progress) {
    let text = printState ? capitalize(printState) : "Unknown";
    if ((printState === "printing" || printState === "paused") && progress !== null && progress !== undefined) {
      text += ` ${num(progress * 100)}%`;
    }
    return text;
  }

  function when(iso) {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    const clock = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (date.toDateString() === new Date().toDateString()) return clock;
    return `${date.toLocaleDateString([], { month: "short", day: "numeric" })} ${clock}`;
  }

  // ---- colours ----------------------------------------------------------------------------

  const MARK_LIGHT = "#FFFFFF";
  const MARK_DARK = "#14171C";

  function hex(text) {
    const match = /^#?([0-9a-f]{6})(?:[0-9a-f]{2})?$/i.exec(String(text || "").trim());
    return match ? `#${match[1].toUpperCase()}` : null;
  }

  function colorsOf(list, fallback) {
    const colors = (Array.isArray(list) ? list : []).map(hex).filter(Boolean);
    if (!colors.length && hex(fallback)) colors.push(hex(fallback));
    return colors;
  }

  function luminance(color) {
    const [r, g, b] = [1, 3, 5].map((i) => {
      const v = parseInt(color.slice(i, i + 2), 16) / 255;
      return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function contrast(a, b) {
    const [la, lb] = [luminance(a), luminance(b)];
    return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
  }

  function markColor(colors) {
    let light = 21;
    let dark = 21;
    for (const color of colors) {
      light = Math.min(light, contrast(color, MARK_LIGHT));
      dark = Math.min(dark, contrast(color, MARK_DARK));
    }
    return light >= dark ? MARK_LIGHT : MARK_DARK;
  }

  function paint(node, colors) {
    if (!colors.length) return false;
    if (colors.length === 1) {
      node.style.background = colors[0];
    } else {
      const step = 100 / colors.length;
      const stops = colors.map((c, i) => `${c} ${num(i * step, 2)}% ${num((i + 1) * step, 2)}%`);
      node.style.background = `linear-gradient(90deg, ${stops.join(", ")})`;
    }
    node.style.color = markColor(colors);
    return true;
  }

  // ---- health (as the touch UI's status line) --------------------------------------------

  function healthSummary() {
    if (!online) return ["error", connectedOnce ? "Offline" : "Connecting"];
    const issues = [];
    const health = state.health || {};
    if (!health.spoolman) issues.push([3, "error", "Spoolman down"]);
    for (const printer of state.printers) {
      if (printer.off) continue;
      if (!printer.connected) {
        issues.push([3, "error", `${printerLabel(printer)} offline`]);
      } else if (printer.afc_error) {
        issues.push([2, "warn", `${printerLabel(printer)} ${isBambu(printer) ? "error" : "AFC error"}`]);
      }
    }
    if (!health.scanner) issues.push([2, "warn", "No scanner"]);
    const scale = state.scale || {};
    if (!scale.present) issues.push([1, "muted", "Scale off"]);
    else if (scale.status === "fault" || scale.status === "calibrate") issues.push([2, "warn", "Scale fault"]);
    else if (scale.status === "over") issues.push([2, "warn", "Scale over"]);
    else if (scale.status === "under" || scale.status === "rezero") issues.push([2, "warn", "Re-zero scale"]);
    if (!issues.length) return ["ok", "All OK"];
    issues.sort((a, b) => b[0] - a[0]);
    return [issues[0][1], issues[0][2] + (issues.length > 1 ? ` +${issues.length - 1}` : "")];
  }

  // ---- rendering --------------------------------------------------------------------------

  function renderHeader() {
    const [level, text] = healthSummary();
    const pill = byId("health");
    pill.className = `pill ${level}`;
    pill.textContent = text;
    const conn = byId("conn");
    conn.querySelector(".dot").className = `dot ${online ? "ok" : "error"}`;
    conn.querySelector(".conn-text").textContent = online ? "Live" : connectedOnce ? "Reconnecting" : "Connecting";
    document.title = `${text} · Spool station`;
    const banner = byId("banner");
    banner.hidden = online;
    banner.textContent = connectedOnce
      ? "Can't reach the station. Showing what it last reported; reconnecting."
      : "Connecting to the station.";
  }

  function renderScale(root) {
    const scale = state.scale || {};
    const spool = state.spool;
    const found = Boolean(spool && spool.found);
    const present = online && scale.present && scale.grams !== null && scale.grams !== undefined;
    const empty = present && scale.grams <= 0;
    root.append(el("h2", null, "Scale"));
    const reading = el("div", `reading${present && !empty ? "" : " dim"}`);
    const decimals = present && Math.abs(scale.grams) < 1000 ? 1 : 0;
    reading.append(el("span", "weight", present ? num(scale.grams, decimals) : "--"));
    if (present) reading.append(el("span", "unit", "g"));
    root.append(reading);

    let check;
    let level = "muted";
    if (!online || !scale.present) {
      check = "Scale off";
    } else if (found && scale.check === "ok" && scale.stable) {
      check = "✓ Matches Spoolman";
      level = "ok";
    } else if (found && scale.check === "warn" && scale.delta_g !== null && scale.delta_g !== undefined) {
      check = `⚠ Off by ${delta(scale.delta_g)}`;
      level = "warn";
    } else if (found && scale.check === "tare_unknown" && scale.stable) {
      check = "Tare unknown";
    } else if (empty) {
      check = "Scale empty";
    } else {
      check = SCALE_LABELS[scale.status] || "Off";
      if (scale.status === "stable") level = "ok";
      else if (scale.status !== "motion") level = "warn";
    }
    root.append(el("span", `pill ${level}`, check));
    if (present && found && scale.net_g !== null && scale.net_g !== undefined) {
      const expected = scale.expected_g !== null && scale.expected_g !== undefined
        ? ` · Spoolman expects ${grams(scale.expected_g)} on the scale` : "";
      root.append(el("div", "sub", `Filament ${grams(scale.net_g)}${expected}`));
    }
  }

  function renderSpool(root) {
    const spool = state.spool;
    root.append(el("h2", null, "Spool"));
    const box = el("div", "spool");
    const tile = el("div", "tile");
    const info = el("div", "spool-info");
    if (spool && spool.found) {
      paint(tile, colorsOf(spool.colors, spool.color));
      if (spool.remaining_g !== null && spool.remaining_g !== undefined) {
        const [value, unit] = compactWeight(spool.remaining_g);
        tile.append(el("b", null, value), el("small", null, `${unit} left`));
      } else {
        tile.append(el("b", null, "?"), el("small", null, "left"));
      }
      info.append(el("div", "head", `#${spool.id}${spool.vendor ? ` · ${spool.vendor}` : ""}`));
      info.append(el("div", "title", spool.name || "Unnamed filament"));
      const details = [spool.material, spool.location].filter(Boolean).join(" · ");
      if (details) info.append(el("div", "meta", details));
      const pct = spool.remaining_g !== null && spool.remaining_g !== undefined && spool.initial_weight_g > 0
        ? clamp((spool.remaining_g / spool.initial_weight_g) * 100) : null;
      const tare = spool.spool_weight_g !== null && spool.spool_weight_g !== undefined
        ? `tare ${grams(spool.spool_weight_g)}` : "tare unknown";
      info.append(el("div", `meta${spool.low_stock ? " warn" : ""}`, `${pct !== null ? `${percent(pct)} left · ` : ""}${tare}`));
      const tags = el("div", "tags");
      if (spool.low_stock) tags.append(el("span", "tag low", "LOW"));
      if (spool.archived) tags.append(el("span", "tag", "ARCHIVED"));
      if (tags.childElementCount) info.append(tags);
      if (spool.last_used) info.append(el("div", "sub", `Last used ${when(spool.last_used)}`));
    } else if (spool) {
      tile.append(el("b", null, "?"), el("small", null, "not found"));
      info.append(el("div", "head", `SPOOL #${spool.id}`), el("div", "title", "Not found in Spoolman"),
        el("div", "meta", spool.message || "Check the ID, or scan the spool's QR code"));
    } else {
      tile.classList.add("dashed");
      tile.append(el("b", null, "—"));
      info.append(el("div", "head", "NO SPOOL SELECTED"), el("div", "title", "Scan a spool"),
        el("div", "meta muted", "at the station"));
    }
    box.append(tile, info);
    root.append(box);
  }

  function renderStation() {
    const root = byId("station");
    root.replaceChildren();
    renderScale(root);
    renderSpool(root);
    const scan = state.scan || {};
    if (scan.countdown) {
      const c = scan.countdown;
      root.append(el("div", "notice info", `${actionLabel(c.action)} spool #${c.spool_id} in ${c.remaining_s} s`));
    }
    if (scan.prompt && scan.prompt.message) root.append(el("div", "notice warn", scan.prompt.message));
    if (scan.last_code) {
      const what = scan.spool_id !== null && scan.spool_id !== undefined ? `#${scan.spool_id}` : scan.last_code;
      root.append(el("div", "sub", `Last scan ${when(scan.at)} · ${what}`));
    }
  }

  function statusText(printer) {
    if (!online) return ["muted", "Service offline"];
    if (printer.off) return ["muted", "Printer off"];
    if (!printer.connected) {
      if (isBambu(printer)) return ["error", "Bambuddy unreachable - retrying"];
      const klippy = printer.klippy_state;
      return ["error", !klippy || klippy === "disconnected" ? "Moonraker unreachable - retrying" : `Klipper ${klippy}`];
    }
    if (printer.afc_error) return ["warn", `⚠ ${printer.afc_error}`];
    const head = isBambu(printer) ? "AMS 3H" : `AFC ${printer.afc_state || "unknown"}`;
    return ["muted", `${head}  |  ${printer.current_load ? `${printer.current_load} loaded` : "nothing loaded"}`];
  }

  function laneRow(lane, loaded) {
    const row = el("li", `lane${loaded ? " loaded" : ""}`);
    const hasSpool = lane.spool_id !== null && lane.spool_id !== undefined;
    const swatch = el("span", `swatch${hasSpool ? "" : " none"}`);
    if (hasSpool) paint(swatch, colorsOf(lane.colors, lane.color));
    const main = el("div", "lane-main");
    main.append(el("div", "lane-name", lane.map ? `${lane.lane}  ${lane.map}` : lane.lane));
    main.append(hasSpool
      ? el("div", "lane-spool", `#${lane.spool_id}${lane.material ? `  ${lane.material}` : ""}`)
      : el("div", "lane-spool none", lane.prep ? "Untagged" : "Empty"));
    const side = el("div", "lane-side");
    const hasWeight = lane.remaining_g !== null && lane.remaining_g !== undefined;
    if (hasWeight) {
      side.append(el("div", `lane-weight${lane.low_stock ? " low" : ""}`, grams(lane.remaining_g)));
      const bar = el("div", `bar${lane.low_stock ? " low" : ""}`);
      const fill = el("span");
      fill.style.width = `${clamp(lane.remaining_g / 10)}%`;
      bar.append(fill);
      side.append(bar);
    }
    const pending = hasSpool && lane.settings_pending;
    const status = pending ? "Settings after print" : lane.filament_status || "";
    side.append(el("div", `lane-status${pending ? " warn" : lane.tool_loaded ? " info" : ""}`, status));
    row.append(swatch, main, side);
    return row;
  }

  function slotTile(lane, loaded) {
    const hasSpool = lane.spool_id !== null && lane.spool_id !== undefined;
    const tile = el("div", `slot${hasSpool ? "" : lane.prep ? " untagged" : " empty"}${loaded ? " loaded" : ""}`);
    tile.append(el("div", "slot-name", lane.lane));
    if (!hasSpool) {
      tile.append(el("div", "slot-empty", lane.prep ? "No tag" : "Empty"));
      return tile;
    }
    paint(tile, colorsOf(lane.colors, lane.color));
    tile.append(el("div", "slot-id", `#${lane.spool_id}`), el("div", null, lane.material || "--"));
    if (lane.remaining_g !== null && lane.remaining_g !== undefined) tile.append(el("div", null, grams(lane.remaining_g)));
    if (lane.low_stock) tile.append(el("span", "tag low", "LOW"));
    else tile.append(el("div", null, lane.settings_pending ? "Pending" : lane.filament_status || ""));
    if (lane.settings_pending) tile.append(el("span", "pending"));
    return tile;
  }

  function printerCard(printer) {
    const up = online && printer.connected;
    const off = online && printer.off;
    const card = el("article", `panel printer${up ? "" : " down"}`);
    const head = el("header", "printer-head");
    const dotLevel = !online || off ? "" : !printer.connected ? "error" : printer.afc_error ? "warn" : "ok";
    head.append(el("span", `dot ${dotLevel}`), el("h3", null, printerLabel(printer)));
    let chipLevel = "muted";
    if (up && printer.print_state === "printing") chipLevel = "info";
    else if (up && printer.print_state === "paused") chipLevel = "warn";
    else if (up && printer.print_state === "error") chipLevel = "error";
    else if (up && printer.print_state === "complete") chipLevel = "ok";
    else if (!up && !off) chipLevel = "error";
    const chipText = off ? "Off" : up ? printLabel(printer.print_state, printer.progress) : "Offline";
    head.append(el("span", `pill ${chipLevel}`, chipText));
    card.append(head);

    const [level, status] = statusText(printer);
    const statusNode = el("div", `status ${level}`, status);
    statusNode.title = status;
    card.append(statusNode);

    if (up && (printer.print_state === "printing" || printer.print_state === "paused")) {
      const job = el("div", "job");
      if (printer.filename) {
        const file = el("div", "file", printer.filename);
        file.title = printer.filename;
        job.append(file);
      }
      const progress = el("div", "progress");
      const fill = el("span");
      fill.style.width = `${clamp((printer.progress || 0) * 100)}%`;
      progress.append(fill);
      job.append(progress);
      card.append(job);
    }

    const next = el("div", `next${printer.pending_spool !== null && printer.pending_spool !== undefined ? " set" : ""}`);
    next.textContent = printer.pending_spool !== null && printer.pending_spool !== undefined
      ? `Next spool #${printer.pending_spool}${printer.pending_confirmed ? "  ✓" : "  (sent)"}`
      : "No next spool";
    card.append(next);

    const lanes = Array.isArray(printer.lanes) ? printer.lanes : [];
    const isLoaded = (lane) => lane.tool_loaded || (printer.current_load && printer.current_load === lane.lane);
    if (isBambu(printer)) {
      const grid = el("div", "slots");
      for (const lane of lanes) grid.append(slotTile(lane, isLoaded(lane)));
      card.append(grid);
    } else {
      const list = el("ul", "lanes");
      for (const lane of lanes) list.append(laneRow(lane, isLoaded(lane)));
      card.append(list);
    }
    return card;
  }

  function renderPrinters() {
    const root = byId("printers");
    root.replaceChildren(...state.printers.map(printerCard));
    if (!state.printers.length) root.append(el("div", "panel empty-note", "No printers reported yet."));
  }

  function renderActivity() {
    const root = byId("activity");
    root.replaceChildren();
    for (const entry of state.activity || []) {
      const item = el("li", `entry${entry.ok ? "" : " fail"}${entry.undone ? " undone" : ""}`);
      const stamp = el("time", null, when(entry.at));
      stamp.dateTime = entry.at || "";
      const body = el("div");
      const what = el("div");
      what.append(el("span", "what", actionLabel(entry.action)));
      if (entry.spool_id !== null && entry.spool_id !== undefined) what.append(document.createTextNode(`  #${entry.spool_id}`));
      if (entry.undone) what.append(el("span", "tag", "UNDONE"));
      if (entry.dry_run) what.append(el("span", "tag", "DRY RUN"));
      body.append(what);
      if (entry.message) body.append(el("div", "msg", entry.message));
      item.append(stamp, body, el("span", "result", entry.ok ? "✓" : "✗"));
      root.append(item);
    }
    if (!root.childElementCount) root.append(el("li", "empty-note", "Nothing yet."));
  }

  function renderService() {
    const service = state.service;
    const root = byId("service");
    if (!service) {
      root.textContent = "Read-only view";
      return;
    }
    const parts = [`Station ${service.version}`, `hardware ${service.hardware}`, `printers ${service.printers}`,
      `Spoolman ${service.spoolman}`, service.writes ? "writes on" : "writes off"];
    if (service.bambuddy_writes !== null && service.bambuddy_writes !== undefined) {
      parts.push(service.bambuddy_writes ? "Bambuddy writes on" : "Bambuddy writes off");
    }
    if (service.dry_run) parts.push("dry run");
    root.textContent = `${parts.join(" · ")} · read-only view`;
  }

  const RENDERERS = {
    header: renderHeader, station: renderStation, printers: renderPrinters, activity: renderActivity,
    service: renderService,
  };
  const TOPICS = {
    scale: ["station", "header"], scan: ["station"], spool: ["station"], printer: ["printers", "header"],
    health: ["header"], activity: ["activity"], settings: [], service: ["service"],
  };

  function invalidate(...parts) {
    for (const part of parts) dirty.add(part);
    if (!frame) frame = requestAnimationFrame(flush);
  }

  function flush() {
    frame = 0;
    for (const part of dirty) RENDERERS[part]();
    dirty.clear();
  }

  const everything = () => invalidate(...Object.keys(RENDERERS));

  // ---- live connection --------------------------------------------------------------------

  function apply(topic, data) {
    if (topic === "printer") {
      const index = state.printers.findIndex((p) => p.key === data.key);
      if (index >= 0) state.printers[index] = data;
      else state.printers.push(data);
    } else if (topic in state) {
      state[topic] = data;
    }
    invalidate(...(TOPICS[topic] || []));
  }

  function connect() {
    const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === "snapshot") {
        Object.assign(state, message.data);
        online = true;
        connectedOnce = true;
        retryMs = 1000;
        everything();
      } else if (message.type === "event") {
        apply(message.topic, message.data);
      }
    });
    socket.addEventListener("close", () => {
      if (online) {
        online = false;
        everything();
      }
      setTimeout(connect, retryMs);
      retryMs = Math.min(retryMs * 2, 15000);
    });
  }

  // Entries from before midnight gain their date without any new event.
  setInterval(() => invalidate("activity", "station"), 60000);
  everything();
  connect();
})();
