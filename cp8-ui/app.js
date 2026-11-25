"use strict";

const byId = (name) => document.getElementById(name);
const colors = ["#80edca", "#ffd184", "#80a5f4", "#f7a985", "#e4a7f4"];
const number = (n, digits = 0) => n.toLocaleString("vi-VN", {
  minimumFractionDigits: digits, maximumFractionDigits: digits
});
const make = (tag, text, className) => {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
};
const clock = new Intl.DateTimeFormat("vi-VN", {
  hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: "Asia/Bangkok"
});

function plot(canvas, panel, range, compact = false, multiplier = 1) {
  const series = panel.series.map(({name, values}) => ({
    name, points: values.map(([ts, value]) => [ts, Number(value) * multiplier])
      .filter(([, value]) => Number.isFinite(value))
  }));
  const all = series.flatMap((line) => line.points.map(([, value]) => value));
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label", panel.title + " theo thời gian");
  const render = () => {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = w * ratio;
    canvas.height = h * ratio;
    if (!w || !h || !all.length) return;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    const left = compact ? 0 : 42;
    const right = w - (compact ? 0 : 17);
    const top = 8;
    const bottom = h - (compact ? 2 : 24);
    const peak = Math.max(...all, 0.001) * 1.05;
    const x = (time) => left + (time - range.start) * (right - left) / (range.end - range.start);
    const y = (value) => bottom - value * (bottom - top) / peak;
    if (!compact) {
      ctx.font = "12px system-ui";
      ctx.fillStyle = "#aab9cf";
      ctx.strokeStyle = "#2b3950";
      for (let tick = 0; tick <= 4; tick++) {
        const level = peak * tick / 4;
        const lineY = y(level);
        ctx.beginPath();
        ctx.moveTo(left, lineY);
        ctx.lineTo(right, lineY);
        ctx.stroke();
        ctx.fillText(number(level, peak < 10 ? 2 : 0), 1, lineY + 4);
      }
      ctx.fillText(clock.format(range.start * 1000), left, h - 5);
      ctx.textAlign = "right";
      ctx.fillText(clock.format(range.end * 1000), right, h - 5);
    }
    series.forEach(({points}, index) => {
      ctx.strokeStyle = colors[index % colors.length];
      ctx.lineWidth = compact ? 1.5 : 2;
      ctx.beginPath();
      points.forEach(([time, value], i) => {
        const gap = i > 0 && time - points[i - 1][0] > range.step;
        if (i === 0 || gap) ctx.moveTo(x(time), y(value));
        else ctx.lineTo(x(time), y(value));
      });
      ctx.stroke();
    });
  };
  new ResizeObserver(render).observe(canvas);
}

function dashboard(history) {
  const metrics = [
    ["req/s", 1, 1], ["%", 100, 2], ["ms", 1000, 1], ["", 1, 0],
    ["", 1, 0], ["USD", 1, 4]
  ];
  history.panels.slice(0, metrics.length).forEach((panel, index) => {
    const [unit, multiplier, digits] = metrics[index];
    const last = panel.series[0]?.values.at(-1)?.[1];
    const card = make("article", undefined, "panel kpi");
    const display = last === undefined ? "—" : number(Number(last) * multiplier, digits);
    const canvas = make("canvas");
    card.append(make("small", panel.title), make("strong", [display, unit].filter(Boolean).join(" ")), canvas);
    byId("totals").append(card);
    plot(canvas, panel, history, true, multiplier);
  });
  history.panels.slice(metrics.length).forEach((panel, index) => {
    const card = make("article", undefined, "panel");
    const canvas = make("canvas");
    const legend = make("div", undefined, "legend");
    panel.series.forEach((line, n) => {
      const label = make("span", line.name);
      label.style.setProperty("--series-color", colors[n % colors.length]);
      legend.append(label);
    });
    card.append(make("h3", panel.title), canvas, legend);
    byId(index < 2 ? "traffic-history" : "llm-history").append(card);
    plot(canvas, panel, history);
  });
}

function scaling(scales) {
  const metrics = [
    ["Tổng request", "count", "", 0], ["Thông lượng", "rps", " req/s", 2],
    ["Latency p50", "p50", " ms", 0], ["Latency p95", "p95", " ms", 0],
    ["Latency p99", "p99", " ms", 0], ["Request lỗi", "failures", "", 0]
  ];
  for (const [label, key, unit, digits] of metrics) {
    const row = make("tr");
    const heading = make("th", label);
    heading.scope = "row";
    row.append(heading, ...scales.map((scale) => make("td", number(scale[key], digits) + unit)));
    byId("scale-table").append(row);
  }
  const buttons = [...document.querySelectorAll("[data-metric]")];
  function show(key) {
    const [, , unit, digits] = metrics.find(([, name]) => name === key);
    const max = Math.max(...scales.map((scale) => scale[key]));
    buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.metric === key)));
    byId("bars").replaceChildren(...scales.map((scale) => {
      const row = make("div", undefined, "bar-row");
      const label = make("div", undefined, "bar-label");
      label.append(make("span", scale.replicas + " agent"), make("strong", number(scale[key], digits) + unit));
      const track = make("div", undefined, "track");
      const fill = make("div", undefined, "fill");
      fill.style.width = (max ? scale[key] / max * 100 : 0) + "%";
      track.setAttribute("aria-hidden", "true");
      track.append(fill);
      row.append(label, track);
      return row;
    }));
  }
  buttons.forEach((button) => button.addEventListener("click", () => show(button.dataset.metric)));
  show("rps");
}

function record(container, title, value, detail, alert = false) {
  const row = make("div", undefined, "record");
  row.append(make("strong", title), make("span", value, alert ? "value alert-value" : "value"), make("small", detail));
  byId(container).append(row);
}

function evidence() {
  const figures = [
    ["Grafana · Golden Signals", "grafana-dashboard.png"],
    ["Jaeger · Trace chậm", "jaeger-slow-trace.png"],
    ["Jaeger · Trace lỗi", "jaeger-error-trace.png"],
    ["Prometheus · Hai alert firing", "prometheus-alert-firing.png"]
  ];
  const dialog = byId("viewer");
  byId("close-viewer").addEventListener("click", () => dialog.close());
  for (const [title, file] of figures) {
    const src = "../screenshots/" + file;
    const button = make("button", undefined, "panel evidence");
    button.type = "button";
    const image = make("img");
    image.src = src;
    image.alt = "";
    image.loading = "lazy";
    button.append(image, make("span", title));
    button.addEventListener("click", () => {
      byId("viewer-title").textContent = title;
      byId("full-image").src = src;
      byId("full-image").alt = title;
      dialog.showModal();
    });
    byId("gallery").append(button);
  }
}

const data = window.CP8_DATA;
if (data) {
  byId("run-date").textContent = new Intl.DateTimeFormat("vi-VN", {
    dateStyle: "medium", timeStyle: "medium", timeZone: "Asia/Bangkok"
  }).format(data.history.end * 1000) + " GMT+7";
  dashboard(data.history);
  scaling(data.scales);
  for (const alert of data.alerts) {
    const error = alert.variable === "MOCK_ERROR_RATE";
    const value = error ? number(alert.observed * 100, 2) + "%" : number(alert.observed * 1000, 1) + " ms";
    record("alerts", alert.name, number(alert.seconds, 1) + " s", alert.variable + "=" + alert.injected + " · Giá trị lúc quan sát " + value, true);
  }
  for (const [key, trace] of Object.entries(data.traces)) {
    record("traces", key === "slow" ? "Trace chậm" : "Trace lỗi · HTTP 503",
      number(trace.total_ms, 1) + " ms", trace.id);
  }
  evidence();
} else {
  byId("status").textContent = "Thiếu dữ liệu CP8. Chạy python scripts/build-cp8-ui.py từ thư mục dự án.";
}
