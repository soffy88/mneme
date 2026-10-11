/*
 * Mneme Animator player (mneme.anim/1) — self-hosted, no dependencies.
 *
 * Renders a deterministic, data-only animation timeline as SVG with
 * play / pause / step controls. Security model:
 *   - the timeline is pure data, read from <script id="anim-spec" type="application/json">;
 *   - only whitelisted shape types are drawn, via createElementNS + setAttribute;
 *   - all text goes through textContent; captions are rebuilt from a tag whitelist
 *     (attributes dropped) and math is typeset by the self-hosted KaTeX auto-render
 *     if it is present;
 *   - nothing in the timeline is ever evaluated as code.
 * Runs inside a sandboxed iframe (allow-scripts only, opaque origin).
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var W = 820;
  var H = 520;
  var PAD = 36;
  var COLORS = {
    ink: "#1f2937", muted: "#6b7280", axis: "#9ca3af", curve: "#2563eb", line: "#64748b",
    given: "#0f766e", emphasis: "#dc2626", aux: "#7c3aed", normal: "#ea580c", plane: "#38bdf8",
    ptA: "#db2777", ptB: "#16a34a", vecA: "#db2777", vecB: "#16a34a", left: "#2563eb",
    right: "#d97706", good: "#16a34a", bad: "#dc2626"
  };
  var SHAPE_TYPES = { point: 1, segment: 1, arrow: 1, polyline: 1, polygon: 1, circle: 1, text: 1, bar: 1 };
  var SAFE_TAGS = {
    p: 1, br: 1, b: 1, strong: 1, i: 1, em: 1, span: 1, div: 1, ul: 1, ol: 1, li: 1,
    table: 1, thead: 1, tbody: 1, tr: 1, td: 1, th: 1, sub: 1, sup: 1, code: 1
  };

  function el(tag, attrs, parent) {
    var node = document.createElementNS(NS, tag);
    for (var k in attrs) {
      if (Object.prototype.hasOwnProperty.call(attrs, k)) node.setAttribute(k, String(attrs[k]));
    }
    if (parent) parent.appendChild(node);
    return node;
  }

  function color(name) {
    return Object.prototype.hasOwnProperty.call(COLORS, name) ? COLORS[name] : COLORS.ink;
  }

  function isNum(v) { return typeof v === "number" && isFinite(v); }

  function clone(v) { return JSON.parse(JSON.stringify(v)); }

  // ── caption: whitelist rebuild, then KaTeX auto-render ────────────────────
  function rebuild(src, dst) {
    for (var i = 0; i < src.childNodes.length; i++) {
      var n = src.childNodes[i];
      if (n.nodeType === 3) {
        dst.appendChild(document.createTextNode(n.textContent || ""));
      } else if (n.nodeType === 1) {
        var tag = n.tagName.toLowerCase();
        var out = SAFE_TAGS[tag] ? document.createElement(tag) : document.createElement("span");
        rebuild(n, out);
        dst.appendChild(out);
      }
    }
  }

  function setCaption(node, html) {
    while (node.firstChild) node.removeChild(node.firstChild);
    var doc = new DOMParser().parseFromString(String(html || ""), "text/html");
    rebuild(doc.body, node);
    if (typeof window.renderMathInElement === "function") {
      try {
        window.renderMathInElement(node, {
          delimiters: [
            { left: "$$", right: "$$", display: true },
            { left: "$", right: "$", display: false }
          ],
          throwOnError: false
        });
      } catch (e) { /* leave raw text */ }
    }
  }

  // ── projection ────────────────────────────────────────────────────────────
  function makeProjector(spec, camera) {
    var c = spec.canvas;
    var v = c.view;
    var sx = (W - 2 * PAD) / (v[1] - v[0]);
    var sy = (H - 2 * PAD) / (v[3] - v[2]);
    var s = Math.min(sx, sy);
    var cx = (v[0] + v[1]) / 2;
    var cy = (v[2] + v[3]) / 2;
    if (c.mode === "3d") {
      var t = c.target || [0, 0, 0];
      var az = ((camera && camera.azimuth) || 45) * Math.PI / 180;
      var elv = ((camera && camera.elevation) || 25) * Math.PI / 180;
      var ca = Math.cos(az), sa = Math.sin(az), ce = Math.cos(elv), se = Math.sin(elv);
      return {
        scale: s,
        p: function (pt) {
          var x = pt[0] - t[0], y = pt[1] - t[1], z = pt[2] - t[2];
          var xr = x * ca - z * sa;
          var zr = x * sa + z * ca;
          var yr = y * ce - zr * se;
          return [W / 2 + xr * s, H / 2 - yr * s];
        }
      };
    }
    return {
      scale: s,
      p: function (pt) { return [W / 2 + (pt[0] - cx) * s, H / 2 - (pt[1] - cy) * s]; }
    };
  }

  // ── tweening ──────────────────────────────────────────────────────────────
  function lerp(a, b, k) {
    if (isNum(a) && isNum(b)) return a + (b - a) * k;
    if (Array.isArray(a) && Array.isArray(b) && a.length === b.length) {
      var out = [];
      for (var i = 0; i < a.length; i++) out.push(lerp(a[i], b[i], k));
      return out;
    }
    return k < 1 ? a : b;
  }

  function ease(k) { return k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2; }

  // ── drawing ───────────────────────────────────────────────────────────────
  function drawShape(svg, shape, st, proj, hl) {
    var col = color(st.color || shape.color);
    var wBoost = hl ? 1.8 : 1;
    var g;
    switch (shape.type) {
      case "point": {
        var p = proj.p(st.at);
        el("circle", { cx: p[0], cy: p[1], r: (st.r || 4) * (hl ? 1.5 : 1), fill: col, stroke: "#fff", "stroke-width": 1.5 }, svg);
        if (st.label) {
          var tp = el("text", { x: p[0] + 7, y: p[1] - 7, fill: col, "font-size": 14, "font-weight": hl ? 700 : 500 }, svg);
          tp.textContent = String(st.label);
        }
        break;
      }
      case "segment": {
        var a = proj.p(st.from), b = proj.p(st.to);
        var attrs = { x1: a[0], y1: a[1], x2: b[0], y2: b[1], stroke: col, "stroke-width": (st.width || 1.6) * wBoost, "stroke-linecap": "round" };
        if (st.dashed) attrs["stroke-dasharray"] = "6 5";
        el("line", attrs, svg);
        break;
      }
      case "arrow": {
        var a2 = proj.p(st.from), b2 = proj.p(st.to);
        el("line", { x1: a2[0], y1: a2[1], x2: b2[0], y2: b2[1], stroke: col, "stroke-width": 1.8 * wBoost }, svg);
        var dx = b2[0] - a2[0], dy = b2[1] - a2[1];
        var len = Math.sqrt(dx * dx + dy * dy) || 1;
        var ux = dx / len, uy = dy / len, hs = 10;
        var p1 = [b2[0] - ux * hs - uy * hs * 0.5, b2[1] - uy * hs + ux * hs * 0.5];
        var p2 = [b2[0] - ux * hs + uy * hs * 0.5, b2[1] - uy * hs - ux * hs * 0.5];
        el("polygon", { points: b2[0] + "," + b2[1] + " " + p1[0] + "," + p1[1] + " " + p2[0] + "," + p2[1], fill: col }, svg);
        if (st.label) {
          var ta = el("text", { x: b2[0] + 6, y: b2[1] - 6, fill: col, "font-size": 13 }, svg);
          ta.textContent = String(st.label);
        }
        break;
      }
      case "polyline":
      case "polygon": {
        var pts = [];
        for (var i = 0; i < (st.pts || []).length; i++) pts.push(proj.p(st.pts[i]).join(","));
        if (shape.type === "polyline") {
          var pa = { points: pts.join(" "), fill: "none", stroke: col, "stroke-width": (st.width || 2) * wBoost, "stroke-linejoin": "round" };
          if (st.dashed) pa["stroke-dasharray"] = "6 5";
          el("polyline", pa, svg);
        } else {
          el("polygon", { points: pts.join(" "), fill: col, "fill-opacity": isNum(st.opacity) ? st.opacity : 0.2, stroke: col, "stroke-width": hl ? 2 : 1 }, svg);
        }
        break;
      }
      case "circle": {
        var pc = proj.p(st.at);
        el("circle", { cx: pc[0], cy: pc[1], r: Math.max(1, (st.radius || 1) * proj.scale), fill: col, "fill-opacity": isNum(st.opacity) ? st.opacity : 0.15, stroke: col }, svg);
        break;
      }
      case "text": {
        var pt = proj.p(st.at);
        var anchor = st.anchor === "end" || st.anchor === "middle" ? st.anchor : "start";
        var tt = el("text", { x: pt[0], y: pt[1], fill: col, "font-size": st.size || 14, "text-anchor": anchor, "font-weight": hl ? 700 : 500 }, svg);
        tt.textContent = String(st.text == null ? "" : st.text);
        break;
      }
      case "bar": {
        var pb = proj.p(st.at);
        var full = Math.abs(st.width || 4) * proj.scale;
        var dir = (st.width || 1) < 0 ? -1 : 1;
        var mx = Math.max(Math.abs(st.max || 1), 1e-9);
        var blen = Math.min(1, Math.abs(st.value || 0) / mx) * full;
        var x0 = dir > 0 ? pb[0] : pb[0] - blen;
        g = el("g", {}, svg);
        el("rect", { x: dir > 0 ? pb[0] : pb[0] - full, y: pb[1] - 9, width: full, height: 14, fill: "#f3f4f6", rx: 3 }, g);
        el("rect", { x: x0, y: pb[1] - 9, width: blen, height: 14, fill: hl ? COLORS.bad : col, rx: 3 }, g);
        var tb = el("text", { x: dir > 0 ? pb[0] + blen + 6 : pb[0] - blen - 6, y: pb[1] + 3, fill: COLORS.ink, "font-size": 12, "text-anchor": dir > 0 ? "start" : "end" }, g);
        tb.textContent = String(st.label == null ? st.value : st.label);
        break;
      }
      default:
        break;
    }
  }

  // ── player ────────────────────────────────────────────────────────────────
  function Player(root, spec) {
    var shapes = [];
    var byId = {};
    for (var i = 0; i < spec.shapes.length; i++) {
      var s = spec.shapes[i];
      if (!SHAPE_TYPES[s.type]) continue; // unknown types are ignored, never interpreted
      shapes.push(s);
      byId[s.id] = s;
    }
    // cumulative state per frame
    var states = [];
    var cams = [];
    var cur = {};
    for (var j = 0; j < shapes.length; j++) cur[shapes[j].id] = clone(shapes[j]);
    var cam = (spec.frames[0] && spec.frames[0].camera) || { azimuth: 45, elevation: 25 };
    for (var f = 0; f < spec.frames.length; f++) {
      var fr = spec.frames[f];
      var sets = fr.set || {};
      for (var id in sets) {
        if (!Object.prototype.hasOwnProperty.call(sets, id) || !cur[id]) continue;
        for (var key in sets[id]) {
          if (Object.prototype.hasOwnProperty.call(sets[id], key)) cur[id][key] = clone(sets[id][key]);
        }
      }
      if (fr.camera) cam = fr.camera;
      states.push(clone(cur));
      cams.push(cam);
    }

    // DOM
    var title = document.createElement("h1");
    title.className = "ma-title";
    title.textContent = spec.title || "";
    root.appendChild(title);
    var svg = el("svg", { viewBox: "0 0 " + W + " " + H, class: "ma-stage", role: "img" }, root);
    var readout = document.createElement("div");
    readout.className = "ma-readout";
    root.appendChild(readout);
    var stepTitle = document.createElement("div");
    stepTitle.className = "ma-step-title";
    root.appendChild(stepTitle);
    var caption = document.createElement("div");
    caption.className = "ma-caption";
    root.appendChild(caption);
    var bar = document.createElement("div");
    bar.className = "ma-controls";
    root.appendChild(bar);
    function button(label, testid, fn) {
      var b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.setAttribute("data-testid", testid);
      b.addEventListener("click", fn);
      bar.appendChild(b);
      return b;
    }
    var idx = 0;
    var playing = false;
    var timer = null;
    var anim = null;
    var bPrev = button("⏮ 上一步", "anim-prev", function () { pause(); go(idx - 1); });
    var bPlay = button("▶ 播放", "anim-play", function () { if (playing) pause(); else play(); });
    var bNext = button("下一步 ⏭", "anim-next", function () { pause(); go(idx + 1); });
    var range = document.createElement("input");
    range.type = "range";
    range.min = "0";
    range.max = String(spec.frames.length - 1);
    range.value = "0";
    range.setAttribute("aria-label", "进度");
    range.addEventListener("input", function () { pause(); go(Number(range.value), true); });
    bar.appendChild(range);
    var counter = document.createElement("span");
    counter.className = "ma-counter";
    counter.setAttribute("data-testid", "anim-counter");
    bar.appendChild(counter);

    function render(state, camera, frame) {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      var proj = makeProjector(spec, camera);
      var show = {};
      var hl = {};
      var k;
      for (k = 0; k < (frame.show || []).length; k++) show[frame.show[k]] = 1;
      for (k = 0; k < (frame.highlight || []).length; k++) hl[frame.highlight[k]] = 1;
      // polygons first, then lines, then points/text on top
      var order = { polygon: 0, circle: 0, polyline: 1, segment: 1, arrow: 1, bar: 2, point: 3, text: 3 };
      var list = shapes.filter(function (s) { return show[s.id]; });
      list.sort(function (a, b) { return order[a.type] - order[b.type]; });
      for (k = 0; k < list.length; k++) drawShape(svg, list[k], state[list[k].id], proj, !!hl[list[k].id]);
    }

    function go(n, instant) {
      if (n < 0 || n >= spec.frames.length) return;
      var from = idx;
      idx = n;
      var frame = spec.frames[n];
      stepTitle.textContent = frame.title || "";
      readout.textContent = frame.readout || "";
      setCaption(caption, frame.caption || "");
      counter.textContent = (n + 1) + " / " + spec.frames.length;
      range.value = String(n);
      document.body.setAttribute("data-frame", String(n));
      bPrev.disabled = n === 0;
      bNext.disabled = n === spec.frames.length - 1;
      if (anim) { cancelAnimationFrame(anim); anim = null; }
      if (instant || Math.abs(from - n) !== 1) {
        render(states[n], cams[n], frame);
        return;
      }
      var a = states[from], b = states[n], ca = cams[from], cb = cams[n];
      var dur = Math.min(650, Math.max(150, (frame.duration_ms || 1000) * 0.45));
      var t0 = null;
      function tick(ts) {
        if (t0 === null) t0 = ts;
        var k = ease(Math.min(1, (ts - t0) / dur));
        var mid = {};
        for (var id in b) {
          if (!Object.prototype.hasOwnProperty.call(b, id)) continue;
          var sa = a[id], sb = b[id], m = {};
          for (var key in sb) {
            if (Object.prototype.hasOwnProperty.call(sb, key)) m[key] = sa ? lerp(sa[key], sb[key], k) : sb[key];
          }
          mid[id] = m;
        }
        var cm = { azimuth: lerp(ca.azimuth, cb.azimuth, k), elevation: lerp(ca.elevation, cb.elevation, k) };
        render(mid, cm, frame);
        if (k < 1) anim = requestAnimationFrame(tick);
        else anim = null;
      }
      anim = requestAnimationFrame(tick);
    }

    function schedule() {
      if (!playing) return;
      if (idx >= spec.frames.length - 1) { pause(); return; }
      timer = setTimeout(function () { go(idx + 1); schedule(); }, spec.frames[idx].duration_ms || 1500);
    }
    function play() {
      if (idx >= spec.frames.length - 1) go(0, true);
      playing = true;
      bPlay.textContent = "⏸ 暂停";
      document.body.setAttribute("data-playing", "1");
      schedule();
    }
    function pause() {
      playing = false;
      if (timer) { clearTimeout(timer); timer = null; }
      bPlay.textContent = "▶ 播放";
      document.body.setAttribute("data-playing", "0");
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "ArrowRight") { pause(); go(idx + 1); }
      else if (e.key === "ArrowLeft") { pause(); go(idx - 1); }
      else if (e.key === " ") { e.preventDefault(); if (playing) pause(); else play(); }
    });
    go(0, true);
  }

  function boot() {
    var root = document.getElementById("anim-root");
    var node = document.getElementById("anim-spec");
    if (!root || !node) return;
    var spec;
    try {
      spec = JSON.parse(node.textContent || "{}");
    } catch (e) {
      root.textContent = "动画数据无法解析";
      return;
    }
    if (!spec || spec.spec_version !== "mneme.anim/1" || !Array.isArray(spec.frames) || !Array.isArray(spec.shapes) || !spec.frames.length) {
      root.textContent = "不支持的动画格式";
      return;
    }
    Player(root, spec);
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
