/* MD20 offline molecule viewer — dependency-free Canvas 2D (HCC Lab, NKUST).
 * Scene JSON: {atoms:[{e,n,r,s,k}], bonds:[[i,j]], frames:[[x,y,z,...]], interactions:{frames:[[[i,j,t]]]}}
 *   k = "L" ligand | "P" pocket side chain | "T" Cα trace | "M" metal
 *   t = "h" H-bond candidate | "c" hydrophobic contact | "m" metal coordination (geometric, computed in Python)
 * Drag = rotate, wheel = zoom, ▶ = play frames, 互作 / 表面 toggles.  No network, no WebGL required. */
(function () {
  "use strict";
  var CPK = {C: "#909090", N: "#3050F8", O: "#FF0D0D", S: "#FFFF30", P: "#FF8000", H: "#FFFFFF", F: "#90E050",
             Cl: "#1FF01F", Br: "#A62929", I: "#940094", Zn: "#7D80B0", Fe: "#E06633", Mg: "#8AFF00", Ca: "#3DFF00",
             Cu: "#C88033", Mn: "#9C7AC7", Na: "#AB5CF2"};
  var RAD = {L: 0.42, P: 0.28, T: 0.0, M: 0.75};
  var VDW = {C: 1.7, N: 1.55, O: 1.52, S: 1.8, P: 1.8, Zn: 1.39, Fe: 1.4, Mg: 1.73, Ca: 1.9};
  var HYD = {ALA: 1, VAL: 1, LEU: 1, ILE: 1, MET: 1, PHE: 1, TRP: 1, PRO: 1, TYR: 1, CYS: 1};
  var ICOL = {h: "#FFD23F", c: "#B0B8C0", m: "#C77DFF"};

  function color(a) {
    if (a.k === "L" && a.e === "C") return "#33C24A";
    return CPK[a.e] || "#FF1493";
  }

  function MD20View(canvas, scene, opts) {
    this.c = canvas; this.g = canvas.getContext("2d"); this.s = scene; this.o = opts || {};
    this.f = 0; this.rot = [1, 0, 0, 0, 1, 0, 0, 0, 1]; this.zoom = 1; this.timer = null;
    this.showInter = this.o.interactions !== false; this.showSurface = !!this.o.surface;
    var xyz = scene.frames[0], n = scene.atoms.length, cx = 0, cy = 0, cz = 0, cnt = 0;
    var focus = scene.atoms.map(function (a, i) { return a.k === "L" ? i : -1; }).filter(function (i) { return i >= 0; });
    if (!focus.length) focus = scene.atoms.map(function (_, i) { return i; });
    focus.forEach(function (i) { cx += xyz[3 * i]; cy += xyz[3 * i + 1]; cz += xyz[3 * i + 2]; cnt++; });
    this.ctr = [cx / cnt, cy / cnt, cz / cnt];
    var r = 0;
    for (var i = 0; i < n; i++) {
      var d = Math.hypot(xyz[3 * i] - this.ctr[0], xyz[3 * i + 1] - this.ctr[1], xyz[3 * i + 2] - this.ctr[2]);
      if (scene.atoms[i].k !== "T" && d > r) r = d;
    }
    this.extent = Math.max(r, 6);
    this._bind(); this.draw();
  }

  MD20View.prototype._bind = function () {
    var self = this, last = null;
    this.c.addEventListener("mousedown", function (e) { last = [e.clientX, e.clientY]; });
    window.addEventListener("mouseup", function () { last = null; });
    window.addEventListener("mousemove", function (e) {
      if (!last) return;
      var dx = (e.clientX - last[0]) * 0.01, dy = (e.clientY - last[1]) * 0.01;
      last = [e.clientX, e.clientY];
      self.rot = mul(rotY(dx), mul(rotX(dy), self.rot)); self.draw();
    });
    this.c.addEventListener("wheel", function (e) {
      e.preventDefault(); self.zoom *= e.deltaY < 0 ? 1.1 : 0.9; self.draw();
    }, {passive: false});
  };

  function rotX(t) { var c = Math.cos(t), s = Math.sin(t); return [1, 0, 0, 0, c, -s, 0, s, c]; }
  function rotY(t) { var c = Math.cos(t), s = Math.sin(t); return [c, 0, s, 0, 1, 0, -s, 0, c]; }
  function mul(a, b) {
    var r = new Array(9);
    for (var i = 0; i < 3; i++) for (var j = 0; j < 3; j++)
      r[3 * i + j] = a[3 * i] * b[j] + a[3 * i + 1] * b[3 + j] + a[3 * i + 2] * b[6 + j];
    return r;
  }

  MD20View.prototype.setFrame = function (f) {
    this.f = Math.max(0, Math.min(this.s.frames.length - 1, f)); this.draw();
    if (this.o.onFrame) this.o.onFrame(this.f);
  };

  MD20View.prototype.play = function () {
    var self = this;
    if (this.timer) { clearInterval(this.timer); this.timer = null; return false; }
    this.timer = setInterval(function () { self.setFrame((self.f + 1) % self.s.frames.length); }, 120);
    return true;
  };

  MD20View.prototype.project = function () {
    var xyz = this.s.frames[this.f], n = this.s.atoms.length, R = this.rot, out = new Float64Array(3 * n);
    var W = this.c.width, H = this.c.height, sc = this.zoom * 0.45 * Math.min(W, H) / this.extent;
    for (var i = 0; i < n; i++) {
      var x = xyz[3 * i] - this.ctr[0], y = xyz[3 * i + 1] - this.ctr[1], z = xyz[3 * i + 2] - this.ctr[2];
      out[3 * i] = W / 2 + sc * (R[0] * x + R[1] * y + R[2] * z);
      out[3 * i + 1] = H / 2 - sc * (R[3] * x + R[4] * y + R[5] * z);
      out[3 * i + 2] = R[6] * x + R[7] * y + R[8] * z;
    }
    return {p: out, sc: sc};
  };

  MD20View.prototype.draw = function () {
    var g = this.g, a = this.s.atoms, pr = this.project(), p = pr.p, sc = pr.sc;
    g.fillStyle = this.o.background || "#111418"; g.fillRect(0, 0, this.c.width, this.c.height);
    var items = [];
    this.s.bonds.forEach(function (b) { items.push({z: (p[3 * b[0] + 2] + p[3 * b[1] + 2]) / 2, b: b}); });
    a.forEach(function (at, i) { if (RAD[at.k] > 0) items.push({z: p[3 * i + 2], i: i}); });
    if (this.showSurface) a.forEach(function (at, i) { if (at.k === "P") items.push({z: p[3 * i + 2] - 0.01, i: i, surf: 1}); });
    items.sort(function (u, v) { return u.z - v.z; });
    var zmin = -this.extent, zmax = this.extent;
    items.forEach(function (it) {
      var shade = 0.45 + 0.55 * Math.max(0, Math.min(1, (it.z - zmin) / (zmax - zmin)));
      g.globalAlpha = shade;
      if (it.b) {
        var i = it.b[0], j = it.b[1], ai = a[i], aj = a[j];
        var trace = ai.k === "T" && aj.k === "T";
        g.lineWidth = trace ? 2.2 : (ai.k === "L" || aj.k === "L" ? 0.22 * sc : 0.12 * sc);
        var mx = (p[3 * i] + p[3 * j]) / 2, my = (p[3 * i + 1] + p[3 * j + 1]) / 2;
        g.strokeStyle = trace ? "#7A8FA6" : color(ai);
        g.beginPath(); g.moveTo(p[3 * i], p[3 * i + 1]); g.lineTo(mx, my); g.stroke();
        g.strokeStyle = trace ? "#7A8FA6" : color(aj);
        g.beginPath(); g.moveTo(mx, my); g.lineTo(p[3 * j], p[3 * j + 1]); g.stroke();
      } else if (it.surf) {
        var sa = a[it.i];
        g.globalAlpha = 0.22 * shade;
        g.fillStyle = HYD[sa.r] ? "#C8B273" : "#6A8CC7";
        g.beginPath(); g.arc(p[3 * it.i], p[3 * it.i + 1], (VDW[sa.e] || 1.7) * sc, 0, 2 * Math.PI); g.fill();
      } else {
        var at = a[it.i];
        g.fillStyle = color(at);
        g.beginPath(); g.arc(p[3 * it.i], p[3 * it.i + 1], Math.max(1.5, RAD[at.k] * sc), 0, 2 * Math.PI); g.fill();
      }
    });
    g.globalAlpha = 1;
    var inter = this.s.interactions && this.s.interactions.frames ? this.s.interactions.frames[this.f] || [] : [];
    if (this.showInter && inter.length) {
      g.lineWidth = 1.6;
      inter.forEach(function (x) {
        g.strokeStyle = ICOL[x[2]] || "#FFFFFF";
        g.setLineDash(x[2] === "c" ? [2, 3] : [5, 4]);
        g.beginPath(); g.moveTo(p[3 * x[0]], p[3 * x[0] + 1]); g.lineTo(p[3 * x[1]], p[3 * x[1] + 1]); g.stroke();
      });
      g.setLineDash([]);
    }
    if (this.o.labels !== false) {
      g.fillStyle = "#E8EEF4"; g.font = "11px sans-serif";
      var seen = {};
      a.forEach(function (at, i) {
        if (at.k !== "P" || at.n !== "CA" && at.n !== "CB") return;
        var key = at.r + at.s;
        if (seen[key]) return; seen[key] = 1;
        g.fillText(at.r + at.s, p[3 * i] + 4, p[3 * i + 1] - 4);
      });
    }
    if (this.s.frames.length > 1) {
      g.fillStyle = "#E8EEF4"; g.font = "12px sans-serif";
      var t = this.s.times_ps ? (" · " + this.s.times_ps[this.f].toFixed(0) + " ps") : "";
      g.fillText("frame " + (this.f + 1) + "/" + this.s.frames.length + t, 8, this.c.height - 8);
    }
  };

  window.MD20View = MD20View;
  window.md20Mount = function (el, scene) {
    var cv = document.createElement("canvas");
    cv.width = el.clientWidth || 640; cv.height = Math.round((el.clientWidth || 640) * 0.62);
    cv.style.cursor = "grab"; cv.style.maxWidth = "100%";
    el.appendChild(cv);
    var bar = document.createElement("div"), v, sl = null;
    if (scene.frames.length > 1) {
      var btn = document.createElement("button");
      sl = document.createElement("input");
      btn.textContent = "▶"; sl.type = "range"; sl.min = 0; sl.max = scene.frames.length - 1; sl.value = 0;
      sl.style.width = "60%";
      btn.onclick = function () { btn.textContent = v.play() ? "❚❚" : "▶"; };
      sl.oninput = function () { v.setFrame(+sl.value); };
      bar.appendChild(btn); bar.appendChild(sl);
    }
    function toggle(label, key, on) {
      var b = document.createElement("button");
      b.textContent = (on ? "☑ " : "☐ ") + label; b.style.marginLeft = "6px";
      b.onclick = function () { v[key] = !v[key]; b.textContent = (v[key] ? "☑ " : "☐ ") + label; v.draw(); };
      bar.appendChild(b);
    }
    toggle("互作", "showInter", true);
    toggle("表面", "showSurface", false);
    el.appendChild(bar);
    v = new MD20View(cv, scene, sl ? {onFrame: function (f) { sl.value = f; }} : {});
    return v;
  };
})();
