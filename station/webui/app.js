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

  // ---- spool popover ----------------------------------------------------------------------
  // Hover (or tap, or Enter) on a spool shows its Spoolman details from /api/spools/<id>, with a link to
  // the spool's page in Spoolman. Clicking pins it open; Esc or a click elsewhere closes it.

  const DETAILS_TTL_MS = 30000;
  const RETRY_MS = 5000;
  const details = new Map();
  const loading = new Set();
  const pop = el("div", "popover");
  pop.hidden = true;
  pop.setAttribute("role", "dialog");
  document.body.append(pop);
  let popId = null;
  let popAnchor = null;
  let anchorBox = null;
  let pinned = false;
  let showTimer = 0;
  let hideTimer = 0;

  function spoolTrigger(node, id) {
    node.dataset.spool = String(id);
    node.tabIndex = 0;
    node.classList.add("has-spool");
    node.setAttribute("aria-haspopup", "dialog");
    node.setAttribute("aria-label", `Spool #${id} details`);
  }

  const triggerOf = (target) => (target instanceof Element ? target.closest("[data-spool]") : null);

  async function loadDetails(id) {
    const cached = details.get(id);
    if ((cached && Date.now() < cached.until) || loading.has(id)) return;
    loading.add(id);
    let entry;
    try {
      const response = await fetch(`/api/spools/${id}`, { cache: "no-store" });
      const body = await response.json().catch(() => ({}));
      entry = response.ok
        ? { data: body, until: Date.now() + DETAILS_TTL_MS }
        : { error: body.message || `Spoolman details unavailable (${response.status})`, until: Date.now() + RETRY_MS };
    } catch {
      entry = { error: "Can't reach the station", until: Date.now() + RETRY_MS };
    }
    loading.delete(id);
    details.set(id, entry);
    if (popId === id && !pop.hidden) renderPopover();
  }

  // What the station already knows about a spool, shown until Spoolman answers.
  function knownSpool(id) {
    if (state.spool && state.spool.found && state.spool.id === id) return state.spool;
    for (const printer of state.printers) {
      for (const lane of printer.lanes || []) {
        if (lane.spool_id === id) {
          return { id, material: lane.material, colors: lane.colors, color: lane.color, remaining_g: lane.remaining_g };
        }
      }
    }
    return { id };
  }

  function day(iso) {
    const date = new Date(iso);
    if (!iso || Number.isNaN(date.getTime())) return null;
    return date.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
  }

  const TARE_SOURCES = { filament: "filament default", vendor: "vendor default" };

  function renderPopover() {
    const id = popId;
    const entry = details.get(id);
    const spool = entry && entry.data ? entry.data : knownSpool(id);
    const head = el("div", "pop-head");
    const swatch = el("span", "pop-swatch");
    paint(swatch, colorsOf(spool.colors, spool.color));
    const title = el("div", "pop-title");
    title.append(el("div", "head", `#${id}${spool.vendor ? ` · ${spool.vendor}` : ""}`));
    title.append(el("div", "name", spool.name || (entry && entry.data ? "Unnamed filament" : `Spool #${id}`)));
    const sub = [spool.material, typeof spool.diameter_mm === "number" ? `${spool.diameter_mm} mm` : null];
    if (sub.some(Boolean)) title.append(el("div", "meta", sub.filter(Boolean).join(" · ")));
    head.append(swatch, title);
    const parts = [head];

    if (typeof spool.remaining_g === "number") {
      const initial = typeof spool.initial_weight_g === "number" && spool.initial_weight_g > 0
        ? spool.initial_weight_g : null;
      const pct = initial ? clamp((spool.remaining_g / initial) * 100) : null;
      const remaining = el("div", "pop-remaining");
      remaining.append(el("div", spool.low_stock ? "warn" : null,
        `${grams(spool.remaining_g)} left${initial ? ` of ${grams(initial)}` : ""}${pct !== null ? ` · ${percent(pct)}` : ""}`));
      if (pct !== null) {
        const bar = el("div", `bar${spool.low_stock ? " low" : ""}`);
        const fill = el("span");
        fill.style.width = `${pct}%`;
        bar.append(fill);
        remaining.append(bar);
      }
      parts.push(remaining);
    }

    const places = [];
    const armed = [];
    for (const printer of state.printers) {
      for (const lane of printer.lanes || []) {
        if (lane.spool_id === id) places.push(`${printerLabel(printer)} ${lane.lane}${lane.map ? ` (${lane.map})` : ""}`);
      }
      if (printer.pending_spool === id) armed.push(printerLabel(printer));
    }
    const temps = typeof spool.extruder_temp === "number"
      ? `${num(spool.extruder_temp)} °C${typeof spool.bed_temp === "number" ? ` · bed ${num(spool.bed_temp)} °C` : ""}`
      : null;
    const tare = typeof spool.spool_weight_g === "number"
      ? `${grams(spool.spool_weight_g)}${TARE_SOURCES[spool.tare_source] ? ` (${TARE_SOURCES[spool.tare_source]})` : ""}`
      : entry && entry.data ? "unknown" : null;
    const facts = [
      ["In", places.join(", ")],
      ["Next spool on", armed.join(", ")],
      ["Location", spool.location],
      ["Used", typeof spool.used_weight_g === "number" ? grams(spool.used_weight_g) : null],
      ["Empty spool", tare],
      ["Temperatures", temps],
      ["Lot", spool.lot_nr],
      ["First used", day(spool.first_used)],
      ["Last used", spool.last_used ? when(spool.last_used) : null],
      ["Added", day(spool.registered)],
    ].filter(([, value]) => value);
    if (facts.length) {
      const list = el("dl", "facts");
      for (const [name, value] of facts) list.append(el("dt", null, name), el("dd", null, value));
      parts.push(list);
    }
    if (spool.comment) parts.push(el("p", "pop-comment", spool.comment));
    const tags = el("div", "tags");
    if (spool.low_stock) tags.append(el("span", "tag low", "LOW"));
    if (spool.archived) tags.append(el("span", "tag", "ARCHIVED"));
    if (tags.childElementCount) parts.push(tags);

    if (!entry) parts.push(el("div", "pop-note", "Loading from Spoolman…"));
    else if (entry.error) parts.push(el("div", "pop-note warn", entry.error));
    const url = entry && entry.data && typeof entry.data.spoolman_url === "string" ? entry.data.spoolman_url : "";
    if (/^https?:\/\//i.test(url)) {
      const link = el("a", "pop-link", "Open in Spoolman ↗");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      parts.push(link);
    }
    pop.setAttribute("aria-label", `Spool #${id}`);
    pop.replaceChildren(...parts);
    place();
  }

  // Below the spool, or above it when there's no room; the page may re-render the spool's tile meanwhile,
  // so its last known box is kept.
  function place() {
    if (popAnchor && popAnchor.isConnected) {
      const r = popAnchor.getBoundingClientRect();
      anchorBox = { left: r.left + scrollX, right: r.right + scrollX, top: r.top + scrollY, bottom: r.bottom + scrollY };
    }
    if (!anchorBox || pop.hidden) return;
    const width = pop.offsetWidth;
    const height = pop.offsetHeight;
    const minLeft = scrollX + 8;
    const maxLeft = scrollX + document.documentElement.clientWidth - 8 - width;
    const left = Math.max(minLeft, Math.min((anchorBox.left + anchorBox.right) / 2 - width / 2, maxLeft));
    let top = anchorBox.bottom + 8;
    if (top + height > scrollY + innerHeight - 8 && anchorBox.top - height - 8 >= scrollY + 8) {
      top = anchorBox.top - height - 8;
    }
    pop.style.left = `${Math.round(left)}px`;
    pop.style.top = `${Math.round(top)}px`;
  }

  function openPopover(anchor, pin) {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    popId = Number(anchor.dataset.spool);
    popAnchor = anchor;
    pinned = pin;
    pop.hidden = false;
    renderPopover();
    loadDetails(popId);
  }

  function closePopover() {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
    pop.hidden = true;
    popId = null;
    popAnchor = null;
    anchorBox = null;
    pinned = false;
  }

  document.addEventListener("pointerover", (event) => {
    if (event.pointerType !== "mouse") return;
    const trigger = triggerOf(event.target);
    if (trigger) {
      clearTimeout(hideTimer);
      if (!pop.hidden && popId === Number(trigger.dataset.spool)) {
        popAnchor = trigger;
        return;
      }
      if (pinned) return;
      clearTimeout(showTimer);
      showTimer = setTimeout(() => openPopover(trigger, false), pop.hidden ? 250 : 80);
    } else if (pop.contains(event.target)) {
      clearTimeout(hideTimer);
    }
  });

  document.addEventListener("pointerout", (event) => {
    if (event.pointerType !== "mouse") return;
    const from = triggerOf(event.target) || (pop.contains(event.target) ? pop : null);
    if (!from) return;
    const to = event.relatedTarget instanceof Node ? event.relatedTarget : null;
    const toTrigger = triggerOf(to);
    if (to && (from.contains(to) || pop.contains(to) || (toTrigger && Number(toTrigger.dataset.spool) === popId))) {
      return;
    }
    clearTimeout(showTimer);
    if (!pinned && !pop.hidden) hideTimer = setTimeout(closePopover, 300);
  });

  document.addEventListener("click", (event) => {
    const trigger = triggerOf(event.target);
    if (trigger) {
      if (!pop.hidden && pinned && popId === Number(trigger.dataset.spool)) closePopover();
      else openPopover(trigger, true);
    } else if (!pop.hidden && !pop.contains(event.target)) {
      closePopover();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !pop.hidden) {
      const anchor = popAnchor;
      closePopover();
      if (anchor && anchor.isConnected) anchor.focus();
    } else if ((event.key === "Enter" || event.key === " ") && triggerOf(event.target) === event.target) {
      event.preventDefault();
      openPopover(event.target, true);
    }
  });

  window.addEventListener("resize", () => { if (!pop.hidden) closePopover(); });
  byId("activity").addEventListener("scroll", () => {
    if (popAnchor && popAnchor.closest("#activity")) closePopover();
  }, { passive: true });

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
      spoolTrigger(box, spool.id);
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
    const onScan = el("div", "sub on-scan");
    onScan.append("On scan: ", el("b", null, actionLabel(scan.action || "weigh_load")));
    root.append(onScan);
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

  function remainingPct(lane) {
    if (typeof lane.remaining_pct === "number") return clamp(lane.remaining_pct);
    return typeof lane.remaining_g === "number" ? clamp(lane.remaining_g / 10) : null;
  }

  // One tile per lane or AMS slot, left to right as they sit on the printer.
  function laneTile(lane, loaded, bambu) {
    const hasSpool = lane.spool_id !== null && lane.spool_id !== undefined;
    const tile = el("li", `slot${hasSpool ? "" : lane.prep ? " untagged" : " empty"}${loaded ? " loaded" : ""}`);
    const head = el("div", "slot-head");
    head.append(el("span", "slot-name", lane.lane));
    if (lane.map) head.append(el("span", "slot-tool", lane.map));
    tile.append(head);
    const wide = typeof lane.filament_mm === "number" && Math.abs(lane.filament_mm - 1.75) > 0.2;
    const foot = el("div", "slot-foot");
    if (lane.nozzle) {
      const [diameter, ...type] = lane.nozzle.split(" ");
      const nozzle = el("div", null, `${diameter} nozzle${type.length && !wide ? ` ${type.join(" ")}` : ""}`);
      if (lane.nozzle_detail) nozzle.title = `${lane.map ? `${lane.map}: ` : ""}${lane.nozzle_detail} nozzle`;
      foot.append(nozzle);
    }
    if (wide) foot.append(el("div", "slot-filament", `${lane.filament_mm} mm filament`));
    if (!hasSpool) {
      tile.append(el("div", "slot-empty", lane.prep ? (bambu ? "No tag" : "Untagged") : "Empty"));
      if (!bambu && lane.filament_status) tile.append(el("div", "slot-status", lane.filament_status));
      if (foot.childElementCount) tile.append(foot);
      return tile;
    }
    paint(tile, colorsOf(lane.colors, lane.color));
    spoolTrigger(tile, lane.spool_id);
    tile.append(el("div", "slot-id", `#${lane.spool_id}`), el("div", "slot-material", lane.material || "--"));
    if (lane.remaining_g !== null && lane.remaining_g !== undefined) {
      const weight = el("div", "slot-weight", grams(lane.remaining_g));
      if (lane.low_stock && !lane.wrong_filament) weight.append(el("span", "tag low", "LOW"));
      tile.append(weight);
      const pct = remainingPct(lane);
      if (pct !== null) {
        const bar = el("div", "slot-bar");
        const fill = el("span");
        fill.style.width = `${pct}%`;
        bar.append(fill);
        tile.append(bar);
      }
    }
    if (lane.wrong_filament) {
      const flag = el("span", "tag wrong", "WRONG SIZE");
      flag.title = `This tool takes ${lane.filament_mm} mm filament; the spool's diameter in Spoolman differs.`;
      tile.append(flag);
    }
    const status = lane.settings_pending ? "Settings after print" : lane.filament_status || "";
    if (status) tile.append(el("div", "slot-status", status));
    if (lane.settings_pending) tile.append(el("span", "pending"));
    if (foot.childElementCount) tile.append(foot);
    return tile;
  }

  function printerCard(printer) {
    const up = online && printer.connected;
    const off = online && printer.off;
    const lanes = Array.isArray(printer.lanes) ? printer.lanes : [];
    // As on the touch UI: a printer with more than four lanes (the H3C's nine slots) gets a row to itself.
    const wide = lanes.length > 4;
    const card = el("article", `panel printer${wide ? " wide" : ""}${up ? "" : " down"}`);
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

    const pending = printer.pending_spool !== null && printer.pending_spool !== undefined;
    const next = el("div", `next${pending ? " set" : ""}`);
    if (pending) {
      const ref = el("span", "spool-ref", `#${printer.pending_spool}`);
      spoolTrigger(ref, printer.pending_spool);
      next.append("Next spool ", ref, printer.pending_confirmed ? "  ✓" : "  (sent)");
    } else {
      next.textContent = "No next spool";
    }
    card.append(next);

    const isLoaded = (lane) => lane.tool_loaded || (printer.current_load && printer.current_load === lane.lane);
    const tiles = el("ol", `tiles${wide ? " many" : ""}`);
    tiles.style.setProperty("--n", String(Math.max(lanes.length, 1)));
    for (const lane of lanes) tiles.append(laneTile(lane, isLoaded(lane), isBambu(printer)));
    card.append(tiles);
    return card;
  }

  function renderPrinters() {
    const root = byId("printers");
    const grid = el("div", `printer-grid${state.printers.length === 1 ? " single" : ""}`);
    grid.append(...state.printers.map(printerCard));
    if (!state.printers.length) grid.append(el("div", "panel empty-note", "No printers reported yet."));
    root.replaceChildren(grid);
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
      if (entry.spool_id !== null && entry.spool_id !== undefined) {
        const ref = el("span", "spool-ref", `#${entry.spool_id}`);
        spoolTrigger(ref, entry.spool_id);
        what.append("  ", ref);
      }
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
