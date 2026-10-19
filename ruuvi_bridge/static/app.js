"use strict";
const $ = (id) => document.getElementById(id);
let state,
  token,
  hours = 24,
  points = [],
  editTag = "",
  historyRequest = 0;
let selected = new URLSearchParams(location.search).get("tag") || "";
const number = (value, digits = 1) =>
  value == null
    ? "–"
    : Number(value).toLocaleString("fi-FI", {
        maximumFractionDigits: digits,
        minimumFractionDigits: digits,
      });
const stamp = (time) =>
  new Date(time * 1000).toLocaleString("fi-FI", {
    day: "numeric",
    month: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
function node(tag, text, className) {
  // Sensor names are untrusted input; never interpret them as HTML.
  const element = document.createElement(tag);
  if (text != null) element.textContent = text;
  if (className) element.className = className;
  return element;
}
function button(text, action, secondary = true) {
  const element = node("button", text, secondary ? "secondary" : "");
  element.type = "button";
  element.addEventListener("click", action);
  return element;
}
async function post(path, data) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Ruuvi-Token": token },
    body: JSON.stringify(data),
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || "Toiminto epäonnistui");
  return body;
}
function feedback(message) {
  $("feedback").textContent = message;
}
function options(select, tags, value, emptyLabel) {
  const children = [
    new Option(emptyLabel, ""),
    ...tags.map((s) => new Option(s.name, s.id)),
  ];
  select.replaceChildren(...children);
  select.value = value;
}
function openTag(sensor) {
  editTag = sensor.id;
  $("tag-dialog-title").textContent = sensor.enabled
    ? "Anturin asetukset"
    : "Ota anturi seurantaan";
  $("tag-address").textContent = sensor.id.match(/../g).join(":").toUpperCase();
  $("tag-name").value = sensor.name;
  $("tag-enabled").checked = sensor.enabled || !state.settings.tags[sensor.id];
  $("tag-feedback").textContent = "";
  $("tag-dialog").showModal();
}
function showHistory(id) {
  selected = id;
  $("history-tag").value = id;
  history.replaceState(
    null,
    "",
    "?tag=" + encodeURIComponent(id) + "&view=history",
  );
  loadHistory();
  $("history-title").scrollIntoView({ behavior: "smooth", block: "center" });
}
function renderSensors() {
  const cards = state.sensors.map((sensor) => {
    const card = node("article", null, "sensor");
    const top = node("div", null, "sensor-top");
    const identity = node("div");
    identity.append(
      node("h3", sensor.name, "sensor-name"),
      node(
        "div",
        sensor.id.match(/../g).join(":").toUpperCase(),
        "sensor-address",
      ),
    );
    top.append(
      identity,
      node(
        "span",
        !sensor.enabled
          ? "Löytynyt"
          : sensor.fresh
            ? "Seurannassa"
            : "Ei yhteyttä",
        "pill" + (sensor.enabled && !sensor.fresh ? " stale" : ""),
      ),
    );
    const values = node("div", null, "readings");
    for (const [key, label, unit] of [
      ["humidity", "Kosteus", "%"],
      ["temperature", "Lämpötila", "°C"],
      ["pressure", "Ilmanpaine", "hPa"],
    ]) {
      const group = node("div");
      const value = node("div", number(sensor[key]), "value");
      value.append(node("span", unit, "unit"));
      group.append(node("div", label, "reading-label"), value);
      values.append(group);
    }
    const details = node("div", null, "sensor-details");
    details.append(
      node("span", "Paristo " + number(sensor.battery) + " V"),
      node("span", "Signaali " + number(sensor.rssi, 0) + " dBm"),
    );
    const actions = node("div", null, "sensor-actions");
    if (sensor.enabled) {
      actions.append(
        button("Historia", () => showHistory(sensor.id), false),
        button("Muokkaa", () => openTag(sensor)),
      );
    } else {
      actions.append(button("Ota seurantaan", () => openTag(sensor), false));
      if (state.settings.tags[sensor.id])
        actions.append(button("Historia", () => showHistory(sensor.id)));
    }
    const seen =
      sensor.age == null
        ? "Odotetaan ensimmäistä mittausta"
        : sensor.fresh
          ? "Päivitetty " + Math.round(sensor.age) + " s sitten"
          : "Viimeisin mittaus " +
            stamp(sensor.last_seen) +
            " · arvot ovat vanhentuneet";
    card.append(top, values, details, actions, node("p", seen, "seen"));
    return card;
  });
  $("sensors").replaceChildren(...cards);
  $("empty").hidden = cards.length > 0;
  $("sensor-count").textContent =
    state.sensors.filter((s) => s.enabled).length + " seurannassa";
}
async function refresh() {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) throw new Error();
    state = await response.json();
    token = state.token;
    $("demo").hidden = !state.demo;
    for (const kind of ["bluetooth", "mqtt"]) {
      const status = state.status[kind];
      $(kind + "-status").textContent = status?.message || "Käynnistyy…";
      $(kind + "-status").className = ["scanning", "connected"].includes(
        status?.state,
      )
        ? "good"
        : "bad";
    }
    if (state.status.storage?.state === "error")
      feedback(state.status.storage.message);
    $("unsupported").hidden = !state.unsupported_formats.length;
    $("unsupported").textContent =
      "Havaittiin myös Ruuvi-dataa muodossa " +
      state.unsupported_formats.join(", ") +
      ". Tämä versio tukee RuuviTagin RAWv2-muotoa (5).";
    renderSensors();
    const tracked = state.sensors.filter((s) => state.settings.tags[s.id]);
    if (!selected || !tracked.some((s) => s.id === selected))
      selected = tracked[0]?.id || "";
    options($("history-tag"), tracked, selected, "Valitse anturi");
    if ($("feedback").dataset.connectionError) {
      feedback("");
      delete $("feedback").dataset.connectionError;
    }
  } catch (error) {
    feedback(
      "Yhteys Ruuvi Bridgeen katkesi. Tarkista, että taustaohjelma on käynnissä.",
    );
    $("feedback").dataset.connectionError = "true";
  }
}
async function loadHistory() {
  // A slower previous request must not replace a newly selected range or tag.
  const request = ++historyRequest;
  if (!selected) {
    points = [];
    drawCharts();
    $("export").removeAttribute("href");
    return;
  }
  const query = new URLSearchParams({ tag: selected, hours });
  $("export").href = "/api/export?" + query;
  try {
    const response = await fetch("/api/history?" + query);
    if (!response.ok) throw new Error();
    const data = await response.json();
    if (request !== historyRequest) return;
    points = data.samples;
    drawCharts();
  } catch (error) {
    feedback("Historian haku epäonnistui. Yritä uudelleen.");
  }
}
const metrics = {
  humidity: { label: "Kosteus", unit: "%", color: "#23816c" },
  temperature: { label: "Lämpötila", unit: "°C", color: "#b57932" },
  pressure: { label: "Ilmanpaine", unit: "hPa", color: "#617db2" },
};
function drawCharts() {
  for (const key of Object.keys(metrics)) drawChart(key);
}
function drawChart(key) {
  const canvas = $("chart-" + key);
  const width = canvas.clientWidth,
    height = canvas.clientHeight,
    ratio = devicePixelRatio || 1;
  canvas.width = width * ratio;
  canvas.height = height * ratio;
  const ctx = canvas.getContext("2d");
  ctx.scale(ratio, ratio);
  const samples = points.filter((p) => p[key] != null);
  const { unit, label, color } = metrics[key];
  $("empty-" + key).hidden = samples.length > 0;
  $("empty-" + key).textContent = selected
    ? "Historia kertyy tähän mittausten saapuessa."
    : "Valitse seurattava anturi nähdäksesi historian.";
  $("summary-" + key).replaceChildren();
  if (!samples.length) return;
  const values = samples.map((p) => p[key]);
  const minimum = Math.min(...values),
    maximum = Math.max(...values),
    average = values.reduce((a, b) => a + b, 0) / values.length;
  for (const [label, value] of [
    ["Alin", minimum],
    ["Keskiarvo", average],
    ["Ylin", maximum],
  ]) {
    const item = node("span", label + " ");
    item.append(node("strong", number(value) + " " + unit));
    $("summary-" + key).append(item);
  }
  const padding = Math.max(
    (maximum - minimum) * 0.2,
    key === "pressure" ? 1 : 2,
  );
  const low = minimum - padding,
    high = maximum + padding;
  const left = key === "pressure" ? 56 : 40,
    right = width - 8,
    top = 12,
    bottom = height - 30;
  const end = Date.now() / 1000,
    start = end - hours * 3600;
  const x = (time) => left + ((time - start) / (end - start)) * (right - left);
  const y = (value) => bottom - ((value - low) / (high - low)) * (bottom - top);
  ctx.font = "11px Segoe UI, sans-serif";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const value = low + ((high - low) * i) / 4,
      yy = y(value);
    ctx.strokeStyle = "#e6ebe6";
    ctx.beginPath();
    ctx.moveTo(left, yy);
    ctx.lineTo(right, yy);
    ctx.stroke();
    ctx.fillStyle = "#758078";
    ctx.textAlign = "right";
    ctx.fillText(number(value, 1), left - 9, yy + 4);
  }
  for (let i = 0; i <= 3; i++) {
    const time = start + ((end - start) * i) / 3;
    const label = new Date(time * 1000).toLocaleString(
      "fi-FI",
      hours <= 24
        ? { hour: "2-digit", minute: "2-digit" }
        : { day: "numeric", month: "numeric" },
    );
    ctx.textAlign = i === 0 ? "left" : i === 3 ? "right" : "center";
    ctx.fillText(label, x(time), height - 8);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.beginPath();
  let previous = null;
  // Leave gaps for missing packets instead of suggesting continuous coverage.
  const gap = Math.max(180, ((hours * 3600) / 1440) * 2);
  for (const point of points) {
    if (point[key] == null) {
      previous = null;
      continue;
    }
    if (!previous || point.time - previous.time > gap)
      ctx.moveTo(x(point.time), y(point[key]));
    else ctx.lineTo(x(point.time), y(point[key]));
    previous = point;
  }
  ctx.stroke();
  if (samples.length === 1) {
    ctx.beginPath();
    ctx.arc(x(samples[0].time), y(samples[0][key]), 4, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
  }
  canvas.setAttribute(
    "aria-label",
    `${label}, ${hours} tuntia. Alin ${number(minimum)}, ylin ${number(maximum)} ${unit}.`,
  );
}
$("history-tag").addEventListener("change", () => {
  selected = $("history-tag").value;
  loadHistory();
});
document.querySelectorAll("[data-hours]").forEach((element) =>
  element.addEventListener("click", () => {
    hours = Number(element.dataset.hours);
    document
      .querySelectorAll("[data-hours]")
      .forEach((b) => b.setAttribute("aria-pressed", String(b === element)));
    loadHistory();
  }),
);
$("settings-open").addEventListener("click", () => {
  if (!state) return;
  const cfg = state.settings;
  for (const key of ["mqtt_enabled", "mqtt_tls", "autostart"])
    $(key.replaceAll("_", "-")).checked = cfg[key];
  for (const key of ["mqtt_host", "mqtt_port", "mqtt_username", "tray_metric"])
    $(key.replaceAll("_", "-")).value = cfg[key];
  options(
    $("tray-tag"),
    state.sensors.filter((s) => s.enabled),
    cfg.tray_tag,
    "Ei valintaa",
  );
  $("mqtt-password").value = "";
  $("mqtt-password").placeholder = cfg.has_password
    ? "Tallennettu · tyhjä säilyttää"
    : "Ei salasanaa";
  $("clear-password").checked = false;
  $("settings-feedback").textContent = "";
  $("settings-dialog").showModal();
});
$("settings-close").addEventListener("click", () =>
  $("settings-dialog").close(),
);
$("settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.submitter;
  submit.disabled = true;
  try {
    const values = {};
    for (const key of ["mqtt_enabled", "mqtt_tls", "autostart"])
      values[key] = $(key.replaceAll("_", "-")).checked;
    for (const key of ["mqtt_host", "mqtt_username", "tray_metric", "tray_tag"])
      values[key] = $(key.replaceAll("_", "-")).value;
    values.mqtt_port = Number($("mqtt-port").value);
    values.mqtt_password = $("clear-password").checked
      ? ""
      : $("mqtt-password").value || null;
    await post("/api/settings", values);
    $("settings-dialog").close();
    feedback("Asetukset tallennettu.");
    await refresh();
  } catch (error) {
    $("settings-feedback").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
$("tag-cancel").addEventListener("click", () => $("tag-dialog").close());
$("tag-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = event.submitter;
  submit.disabled = true;
  try {
    await post("/api/tag", {
      id: editTag,
      name: $("tag-name").value,
      enabled: $("tag-enabled").checked,
    });
    $("tag-dialog").close();
    feedback("Anturin asetukset tallennettu.");
    await refresh();
    await loadHistory();
  } catch (error) {
    $("tag-feedback").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
for (const key of Object.keys(metrics))
  new ResizeObserver(drawCharts).observe($("chart-" + key).parentElement);
async function poll() {
  // Schedule after completion so slow requests cannot overlap the next poll.
  await refresh();
  await loadHistory();
  setTimeout(poll, 5000);
}
poll();
