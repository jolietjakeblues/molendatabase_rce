(function () {
  "use strict";
  var DIRS = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"];
  var DIRNAAM = { N: "noord", NO: "noordoost", O: "oost", ZO: "zuidoost", Z: "zuid", ZW: "zuidwest", W: "west", NW: "noordwest" };
  var KLEUR = { Goed: "#39870C", Matig: "#E17000", Slecht: "#D52B1E", "": "#94A3B8" };
  var BRON = [
    ["Monumentnummer", "RCE monumentenregister"], ["Naam", "RCE naam of quote uit omschrijving"],
    ["Jaar bouw", "RCE datering, omschrijving of BAG-bouwjaar"], ["Jaar herbouw", "Omschrijving (tekstherkenning)"],
    ["Brand jaar", "Omschrijving (tekstherkenning)"], ["Straat", "BAG via RCE, anders PDOK Locatieserver"],
    ["Huisnr.", "BAG via RCE, anders PDOK Locatieserver"], ["Postcode", "BAG via RCE, anders PDOK Locatieserver"],
    ["Plaats", "BAG via RCE, anders PDOK Locatieserver"], ["Gemeente", "RCE (OWMS)"], ["Provincie", "RCE (OWMS)"],
    ["Eigenaar", "Omschrijving, zelden vermeld"], ["Laatste restauratie jaar", "Omschrijving (tekstherkenning)"],
    ["Aandrijving", "Afgeleid uit omschrijving; standaard windmolen"], ["TYPE WINDMOLEN", "Omschrijving (tekstherkenning)"],
    ["Plaatsing van de molen", "Omschrijving (tekstherkenning)"], ["Functie", "Omschrijving (tekstherkenning)"],
    ["Hiudige Bestemming", "Omschrijving, alleen bij nieuwere teksten"], ["Bouwkenmerken", "Omschrijving (tekstherkenning)"],
    ["Romptype", "Omschrijving (tekstherkenning)"], ["Versieringen", "Omschrijving (tekstherkenning)"],
    ["Wieksysteem:", "Omschrijving, zelden vermeld"], ["Vlucht", "Omschrijving, zelden vermeld"],
    ["Erf:", "Omschrijving: alleen 'Ja' als genoemd"], ["Molenbiotoop", "Berekend uit AHN + BAG (zie uitleg)"]
  ];
  var KLEUR_REL = "#42145F", RELKLEUR = { "zelfde perceel": "#D52B1E", tegenaan: "#D52B1E", "aangrenzend perceel": "#E17000", "ander perceel": "#94A3B8", "de molen zelf": "#000000" };
  var LAATSTE_TPL = "Molenbiotoop: NW";

  var modus = "wind", normLayer, zoneLayer, erfLayer, data, rows, filtered = [], map, layer, markers = {}, gezLayer, sortKey = "nr", sortDir = 1, selected = null, vink = {};

  function key(row, prefix) { for (var k in row) if (k.indexOf(prefix) === 0) return k; return null; }
  function val(row, prefix) { var k = key(row, prefix); return k ? row[k] : ""; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function overall(m) {
    var s = m.biotoop && m.biotoop.score;
    if (!s) return { klasse: "", gem: null };
    if (modus === "wind" && m.wind) return { klasse: m.wind.klasse_energie, gem: m.wind.index_energie };
    var v = DIRS.map(function (d) { return s[d]; }), g = v.reduce(function (a, b) { return a + b; }, 0) / v.length;
    return { klasse: g < 0.15 ? "Goed" : g < 0.45 ? "Matig" : "Slecht", gem: g };
  }

  function prep(m) {
    var r = m.row;
    m._o = overall(m);
    m._prov = r["Provincie"]; m._plaats = r["Plaats"]; m._gem = r["Gemeente"];
    m._cat = m.categorie || "Molen";
    m._zone = m.zone ? m.zone.status : "";
    m._norm = m.norm ? m.norm.uitkomst : "";
    m._type = m._cat === "Molen" ? val(r, "TYPE WINDMOLEN") : r["Functie volgens RCE-thesaurus (oorspronkelijk)"];
    m._gez = r["Binnen beschermd stads-/dorpsgezicht (Ja/Nee)"];
    m._jaar = parseInt(r["Jaar bouw"], 10) || null;
    m._zoek = [m.nr, m.naam, r["Plaats"], r["Straat"], r["Gemeente"], r["Omschrijving RCE"]].join(" ").toLowerCase();
  }

  function fillSelect(id, vals) {
    var el = document.getElementById(id);
    Array.from(new Set(vals.filter(Boolean))).sort(function (a, b) { return a.localeCompare(b, "nl"); }).forEach(function (v) {
      var o = document.createElement("option"); o.textContent = v; el.appendChild(o);
    });
  }

  function init(d) {
    data = d; rows = d.molens; rows.forEach(prep);
    var nm = rows.filter(function (m) { return m._cat === "Molen"; }).length;
    document.getElementById("n-totaal").textContent = nm;
    document.getElementById("n-rel").textContent = rows.length - nm;
    document.getElementById("n2").textContent = nm;
    fillSelect("f-provincie", rows.map(function (m) { return m._prov; }));
    fillSelect("f-gemeente", rows.map(function (m) { return m._gem; }));
    fillSelect("f-type", rows.map(function (m) { return m._type; }));
    initMap(); dekking(); bind(); apply();
  }

  function initMap() {
    map = L.map("map", { scrollWheelZoom: false }).setView([52.0, 4.5], 9);
    L.tileLayer("https://service.pdok.nl/brt/achtergrondkaart/wmts/v2_0/standaard/EPSG:3857/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "Kaart: BRT-achtergrondkaart © Kadaster/PDOK"
    }).addTo(map);
    layer = L.layerGroup().addTo(map);
    fetch("data/gezichten.geojson").then(function (r) { return r.json(); }).then(function (g) {
      gezLayer = L.geoJSON(g, {
        style: { color: "#7a4fa3", weight: 1.5, fillColor: "#7a4fa3", fillOpacity: 0.12 },
        onEachFeature: function (f, l) { l.bindTooltip(f.properties.naam + " (" + f.properties.soort + ")", { sticky: true }); }
      }).addTo(map);
      gezLayer.bringToBack();
    }).catch(function () {});
  }

  function bind() {
    ["q", "f-categorie", "f-zone", "f-norm", "f-provincie", "f-gemeente", "f-type", "f-gezicht", "f-bio"].forEach(function (id) {
      document.getElementById(id).addEventListener("input", apply);
    });
    document.getElementById("reset").addEventListener("click", function () {
      ["q", "f-categorie", "f-zone", "f-norm", "f-provincie", "f-gemeente", "f-type", "f-gezicht", "f-bio"].forEach(function (id) { document.getElementById(id).value = ""; });
      apply();
    });
    document.getElementById("toggle-gezichten").addEventListener("change", function (e) {
      if (!gezLayer) return;
      if (e.target.checked) gezLayer.addTo(map); else map.removeLayer(gezLayer);
    });
    document.querySelectorAll('input[name="modus"]').forEach(function (r) {
      r.addEventListener("change", function () {
        modus = r.value; rows.forEach(function (m) { m._o = overall(m); }); apply();
        if (selected) { var cur = rows.find(function (x) { return x.nr === selected; }); if (cur) select(cur, false); }
      });
    });
    document.getElementById("dl-sel").addEventListener("click", downloadSelectie);
    document.getElementById("wis-vink").addEventListener("click", function () { vink = {}; renderTable(); updateSel(); });
    document.getElementById("vink-alle").addEventListener("change", function (e) {
      filtered.forEach(function (m) { if (e.target.checked) vink[m.nr] = true; else delete vink[m.nr]; });
      renderTable(); updateSel();
    });
    document.querySelectorAll("#tabel th[data-k]").forEach(function (th) {
      th.addEventListener("click", function () {
        var k = th.dataset.k; if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
        renderTable();
      });
    });
  }

  function apply() {
    var q = document.getElementById("q").value.trim().toLowerCase(),
      c = document.getElementById("f-categorie").value, zo = document.getElementById("f-zone").value, no = document.getElementById("f-norm").value, p = document.getElementById("f-provincie").value, g = document.getElementById("f-gemeente").value, t = document.getElementById("f-type").value,
      z = document.getElementById("f-gezicht").value, b = document.getElementById("f-bio").value;
    filtered = rows.filter(function (m) {
      return (!q || m._zoek.indexOf(q) >= 0) && (!c || m._cat === c) && (!zo || m._zone === zo) && (!no || m._norm === no) && (!p || m._prov === p) && (!g || m._gem === g) && (!t || m._type === t) &&
        (!z || m._gez === z) && (!b || m._o.klasse === b);
    });
    document.getElementById("telling").textContent = filtered.length + " van " + rows.length + " molens";
    renderMap(); renderTable(); updateSel();
  }

  function selectie() {
    var n = Object.keys(vink).length;
    return n ? rows.filter(function (m) { return vink[m.nr]; }) : filtered;
  }

  function updateSel() {
    var n = Object.keys(vink).length, sel = selectie();
    document.getElementById("dl-sel").textContent = "Download selectie (" + sel.length + (sel.length === 1 ? " rij" : " rijen") + ", CSV)";
    document.getElementById("dl-sel").disabled = !sel.length;
    document.getElementById("wis-vink").hidden = !n;
    document.getElementById("wis-vink").textContent = "Wis " + n + " aangevinkte " + (n === 1 ? "rij" : "rijen");
    document.getElementById("sel-uitleg").textContent = n
      ? "Je downloadt de " + n + " aangevinkte rijen. Alle kolommen zitten altijd in de download."
      : "De selectie is wat de filters tonen. Vink rijen in de lijst aan om alleen die te downloaden. Alle kolommen zitten altijd in de download.";
    var all = document.getElementById("vink-alle");
    all.checked = filtered.length > 0 && filtered.every(function (m) { return vink[m.nr]; });
  }

  function csvCel(v) {
    v = v == null ? "" : String(v);
    return /[;"\r\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v;
  }

  function downloadSelectie() {
    var sel = selectie(), cols = data.kolommen;
    if (!sel.length) return;
    var regels = [cols.map(csvCel).join(";")].concat(sel.map(function (m) { return cols.map(function (c) { return csvCel(m.row[c]); }).join(";"); }));
    var blob = new Blob(["﻿" + regels.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
    var a = document.createElement("a"), d = new Date().toISOString().slice(0, 10);
    a.href = URL.createObjectURL(blob); a.download = "molens-selectie-" + d + ".csv";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }

  function renderMap() {
    layer.clearLayers(); markers = {};
    filtered.forEach(function (m) {
      var rel = m._cat !== "Molen", c = rel ? KLEUR_REL : KLEUR[m._o.klasse];
      var mk = L.circleMarker([m.lat, m.lon], { radius: rel ? 6 : 7, color: rel ? "#fff" : "#10181b", weight: rel ? 2 : 1, fillColor: c, fillOpacity: 0.95 });
      mk.bindTooltip(esc(m.naam) + " · " + esc(m._plaats));
      mk.on("click", function () { select(m, false); });
      mk.addTo(layer); markers[m.nr] = mk;
    });
    map.invalidateSize();
    if (filtered.length && filtered.length < rows.length) {
      map.fitBounds(L.latLngBounds(filtered.map(function (m) { return [m.lat, m.lon]; })).pad(0.2), { maxZoom: 14 });
    } else if (filtered.length === rows.length) {
      map.fitBounds(L.latLngBounds(rows.map(function (m) { return [m.lat, m.lon]; })).pad(0.05));
    }
  }

  function renderTable() {
    var f = { nr: function (m) { return parseInt(m.nr, 10); }, naam: function (m) { return m.naam.toLowerCase(); },
      plaats: function (m) { return (m._plaats || "").toLowerCase(); }, gemeente: function (m) { return (m._gem || "").toLowerCase(); },
      jaar: function (m) { return m._jaar || 9999; }, type: function (m) { return (m._type || "zzz").toLowerCase(); },
      gezicht: function (m) { return m._gez; }, zone: function (m) { return m._zone; }, bio: function (m) { return m._o.gem == null ? 9 : m._o.gem; } }[sortKey];
    var list = filtered.slice().sort(function (a, b) { var x = f(a), y = f(b); return (x < y ? -1 : x > y ? 1 : 0) * sortDir; });
    var tb = document.querySelector("#tabel tbody");
    tb.innerHTML = list.map(function (m) {
      return '<tr data-nr="' + m.nr + '"' + (selected === m.nr ? ' class="sel"' : "") + '><td class="chk"><input type="checkbox" class="vink" aria-label="Selecteer ' + esc(m.naam) + '"' + (vink[m.nr] ? " checked" : "") + "></td><td>" + m.nr + "</td><td>" + esc(m.naam) + "</td><td>" + esc(m._plaats) + "</td><td>" + esc(m._gem) +
        "</td><td>" + (m._jaar || "") + "</td><td>" + esc(m._type) + "</td><td>" + esc(m._gez) + "</td><td>" + esc(m._zone) + "</td><td>" +
        (m._o.klasse ? '<span class="tag ' + m._o.klasse + '">' + m._o.klasse + "</span>" : "") + "</td></tr>";
    }).join("");
    tb.querySelectorAll("tr").forEach(function (tr) {
      var cb = tr.querySelector(".vink");
      cb.addEventListener("click", function (e) { e.stopPropagation(); });
      cb.addEventListener("change", function () { if (cb.checked) vink[tr.dataset.nr] = true; else delete vink[tr.dataset.nr]; tr.classList.toggle("vink", cb.checked); updateSel(); });
      tr.classList.toggle("vink", !!vink[tr.dataset.nr]);
      tr.addEventListener("click", function () {
        var m = rows.find(function (x) { return x.nr === tr.dataset.nr; }); select(m, true);
      });
    });
  }

  function relTag(r) { return '<span class="tag rel-' + (r === "zelfde perceel" || r === "tegenaan" ? "erf" : r === "aangrenzend perceel" ? "adj" : "ver") + '">' + esc(r) + "</span>"; }

  function erfHtml(m) {
    var e = m.erf; if (!e) return "";
    var t = e.tel || {}, h = "<strong>Erf en kadastrale percelen</strong>";
    h += '<dl class="kv"><dt>Perceel molen</dt><dd>' + esc((e.molenpercelen || []).join("; ")) + (e.molenperceel_m2 ? " (" + e.molenperceel_m2 + " m²)" : "") + "</dd>" +
      "<dt>Gebouwen (BAG)</dt><dd>" + (t.tegenaan || 0) + " tegenaan · " + (t["zelfde perceel"] || 0) + " zelfde perceel · " + (t["aangrenzend perceel"] || 0) + " aangrenzend · " + (t["ander perceel"] || 0) + " ander perceel (binnen 100 m)</dd>" +
      "<dt>Op het erf</dt><dd>" + (e.woning_op_erf ? "woning" : "geen woning") + ", " + (e.bijgebouwen_op_erf || 0) + " bijgebouw(en)</dd></dl>";
    if ((e.gerelateerd || []).length) h += "<p>Gerelateerde rijksmonumenten: " + e.gerelateerd.map(function (g) { return esc(g.functies[0]) + " " + g.rijksmonumentnummer + " " + relTag(g.relatie); }).join(", ") + "</p>";
    if ((e.dichtstbij || []).length) h += '<ul class="erflijst">' + e.dichtstbij.map(function (d) {
      return "<li>" + d.afstand + " m " + relTag(d.relatie) + " " + esc(d.gebruik) + (d.bouwjaar && d.bouwjaar !== 9999 ? ", " + d.bouwjaar : "") + (d.rijksmonument ? ", rijksmonument " + d.rijksmonument.nr : "") + "</li>";
    }).join("") + "</ul>";
    return h;
  }

  function erfOpKaart(m, pan) {
    if (erfLayer) { map.removeLayer(erfLayer); erfLayer = null; }
    if (m._cat !== "Molen" || !m.erf) return;
    fetch("data/erf/" + m.nr + ".json").then(function (r) { return r.json(); }).then(function (g) {
      if (selected !== m.nr) return;
      erfLayer = L.geoJSON(g, {
        style: function (f) {
          var p = f.properties;
          if (p.soort === "perceel") return p.molenperceel ? { color: "#FFB612", weight: 3, fillColor: "#FFB612", fillOpacity: 0.15 } : { color: "#475569", weight: 1, dashArray: "4 3", fill: false };
          if (p.soort === "pand") return { color: p.rijksmonument ? "#42145F" : "#000", weight: p.rijksmonument ? 3 : 1, fillColor: RELKLEUR[p.relatie] || "#94A3B8", fillOpacity: 0.6 };
          return { color: "#000", weight: 2, fillColor: "#000", fillOpacity: 0.8 };
        },
        pointToLayer: function (f, ll) { return L.circleMarker(ll, { radius: 4, color: "#000", fillColor: "#000", fillOpacity: 1 }); },
        onEachFeature: function (f, l) {
          var p = f.properties;
          if (p.soort === "pand") l.bindTooltip(p.relatie + ", " + p.afstand + " m, " + p.gebruik + (p.bouwjaar && p.bouwjaar !== 9999 ? ", " + p.bouwjaar : "") + (p.rijksmonument ? ", rijksmonument " + p.rijksmonument.nr : ""));
          else if (p.soort === "perceel") l.bindTooltip("Perceel " + p.perceel + (p.m2 ? " (" + p.m2 + " m²)" : "") + (p.molenperceel ? ", perceel van de molen" : ""));
        }
      }).addTo(map);
      markers[m.nr] && markers[m.nr].bringToFront();
      var bb = null;
      erfLayer.eachLayer(function (l) {
        var so = l.feature && l.feature.properties.soort;
        if (so === "pand" || so === "molen") { var b2 = l.getBounds ? l.getBounds() : L.latLngBounds([l.getLatLng()]); bb = bb ? bb.extend(b2) : L.latLngBounds(b2.getSouthWest(), b2.getNorthEast()); }
      });
      if (bb) map.fitBounds(bb.pad(0.25), { maxZoom: 19 });
    }).catch(function () {});
  }

  function rose(m) {
    var b = m.biotoop || {}, kl = b.klasse || {}, dom = b.dominant || {}, s = b.score || {}, w = m.wind ? m.wind.energie : null;
    var cx = 95, cy = 95, R = 58, out = "";
    DIRS.forEach(function (d, i) {
      var a0 = (i * 45 - 22.5 - 90) * Math.PI / 180, a1 = (i * 45 + 22.5 - 90) * Math.PI / 180;
      var x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0), x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
      var c = KLEUR[kl[d] || ""];
      var o = dom[d] ? dom[d].type + " van " + String(dom[d].hoogte).replace(".", ",") + " m op " + dom[d].afstand + " m" : "geen obstakel dat telt";
      out += '<path d="M' + cx + " " + cy + " L" + x0.toFixed(1) + " " + y0.toFixed(1) + " A" + R + " " + R + " 0 0 1 " + x1.toFixed(1) + " " + y1.toFixed(1) + ' Z" fill="' + c + '" stroke="var(--paper)" stroke-width="2"><title>Wind uit ' + DIRNAAM[d] + ": " + (kl[d] || "onbekend") + " (" + (s[d] != null ? s[d].toFixed(2) : "-") + "). Zwaarste obstakel: " + o + "</title></path>";
      if (w) {
        var r1 = R + 15, r2 = r1 + w[i] * 48, b0 = (i * 45 - 17 - 90) * Math.PI / 180, b1 = (i * 45 + 17 - 90) * Math.PI / 180;
        var p = function (r, a) { return (cx + r * Math.cos(a)).toFixed(1) + " " + (cy + r * Math.sin(a)).toFixed(1); };
        out += '<path d="M' + p(r1, b0) + " L" + p(r2, b0) + " A" + r2.toFixed(1) + " " + r2.toFixed(1) + " 0 0 1 " + p(r2, b1) + " L" + p(r1, b1) + " A" + r1 + " " + r1 + " 0 0 0 " + p(r1, b0) + ' Z" fill="#FFB612" stroke="#000" stroke-width=".6"><title>Aandeel windenergie uit ' + DIRNAAM[d] + ": " + Math.round(w[i] * 100) + "%</title></path>";
      }
      var lx = cx + (R + 8) * Math.cos((i * 45 - 90) * Math.PI / 180), ly = cy + (R + 8) * Math.sin((i * 45 - 90) * Math.PI / 180);
      out += '<text x="' + lx.toFixed(1) + '" y="' + (ly + 3.5).toFixed(1) + '" text-anchor="middle" font-size="9" fill="currentColor">' + d + "</text>";
    });
    out += '<circle cx="' + cx + '" cy="' + cy + '" r="6" fill="var(--paper)" stroke="currentColor"/>';
    var lijst = DIRS.map(function (d, i) {
      return "<li><strong>" + d + "</strong> " + (kl[d] ? '<span class="tag ' + kl[d] + '">' + kl[d] + "</span>" : "–") + (w ? ' <span class="wnd">' + Math.round(w[i] * 100) + "% wind</span>" : "") +
        (dom[d] ? " " + dom[d].type + " " + String(dom[d].hoogte).replace(".", ",") + " m op " + dom[d].afstand + " m" : "") + "</li>";
    }).join("");
    return '<div class="rose"><svg viewBox="0 0 190 190" role="img" aria-label="Molenbiotoop per windrichting, met aandeel windenergie in geel">' + out + "</svg><ul>" + lijst + "</ul></div>";
  }

  function windHtml(m) {
    var w = m.wind; if (!w) return "";
    var tag = function (k) { return '<span class="tag ' + k + '">' + k + "</span>"; };
    return '<dl class="kv"><dt>Windgewogen (energie)</dt><dd>' + tag(w.klasse_energie) + " index " + String(w.index_energie).replace(".", ",") + "</dd>" +
      "<dt>Windgewogen (frequentie)</dt><dd>" + tag(w.klasse_freq) + " index " + String(w.index_freq).replace(".", ",") + "</dd>" +
      "<dt>Zonder weging</dt><dd>" + tag(w.klasse_gemiddeld) + " index " + String(w.index_gemiddeld).replace(".", ",") + "</dd>" +
      "<dt>Overheersende wind</dt><dd>" + esc(w.overheersend_energie) + " (energie)</dd>" +
      "<dt>Windroos uit</dt><dd>" + w.stations.map(function (q) { return esc(q.naam) + " " + Math.round(q.gewicht * 100) + "% (" + q.afstand_km + " km)"; }).join(", ") + ", KNMI " + esc(w.periode) + "</dd></dl>" +
      '<p class="note">Gele staven in de windroos: aandeel van de windenergie per richting.</p>';
  }

  function zoneHtml(m) {
    var z = m.zone; if (!z) return "";
    var h = "<strong>Formele molenbiotoopzone</strong>";
    if (z.status !== "Ja") return h + '<p class="zonenote"><span class="tag zone-' + z.status + '">' + z.status + "</span> " + esc(z.reden || "") + "</p>" + (z.vergelijking ? '<p class="note">' + esc(z.vergelijking) + "</p>" : "");
    var zl = (z.zones || []).map(function (q) {
      return "<li>" + esc(q.naam) + (q.straal_m ? ", straal " + q.straal_m + " m" : "") + '<br><span class="note">' + esc(q.plan_dossier || "") + ", " + esc(q.planstatus || "") + " " + esc(q.plandatum || "") +
        (q.plantekst ? ' · <a href="' + esc(q.plantekst) + '" target="_blank" rel="noopener">plantekst</a>' : "") + "</span>" + normHtml(q) + "</li>";
    }).join("");
    h += '<ul class="zonelijst">' + zl + "</ul>";
    h += '<dl class="kv"><dt>Dekking cirkel</dt><dd>' + Math.round(z.dekking_100m * 100) + "% van 100 m, " + Math.round(z.dekking_400m * 100) + "% van 400 m</dd>" +
      "<dt>Gebouwen in zone</dt><dd>" + z.gebouwen_in_zone + " (BAG), waarvan " + z.gebouwen_jonger_dan_plan + " gebouwd na plandatum</dd>" +
      (z.hoge_objecten_aandeel != null ? "<dt>Hoge objecten</dt><dd>" + Math.round(z.hoge_objecten_aandeel * 100) + "% van de zone ≥ 3 m, hoogste " + String(z.hoogste_obstakel_m).replace(".", ",") + " m (AHN)</dd>" : "") +
      (z.gevonden_op && z.gevonden_op !== "op de molen" ? "<dt>Let op</dt><dd>zone gevonden " + esc(z.gevonden_op) + ", niet op het molenpunt</dd>" : "") +
      (z.molenaanduidingen && z.molenaanduidingen.length ? "<dt>Aanduiding in plan</dt><dd>" + esc(z.molenaanduidingen.map(function (a) { return a.naam; }).filter(function (v, i, a) { return a.indexOf(v) === i; }).join("; ")) + "</dd>" : "") + "</dl>";
    return h + normToetsHtml(m) + '<p class="note">' + esc(z.vergelijking) + ".</p>";
  }

  function normToetsHtml(m) {
    var n = m.norm; if (!n) return "";
    var cls = { "Voldoet": "Goed", "Afhankelijk van wiekhoogte": "Matig", "Overschrijding": "Slecht", "Niet getoetst": "" }[n.uitkomst] || "";
    var h = "<strong>Normtoets: hoogte volgens het plan</strong><p>" + (cls ? '<span class="tag ' + cls + '">' + esc(n.uitkomst) + "</span>" : '<span class="tag zone-Onbekend">' + esc(n.uitkomst) + "</span>");
    if (!n.norm) return h + " " + esc(n.reden || "") + "</p>";
    var g = n.gebouwen_boven_norm, a = n.aanname;
    h += " " + g.midden + " gebouw" + (g.midden === 1 ? "" : "en") + " boven de norm (" + g.streng + " bij strenge, " + g.ruim + " bij ruime aanname van de wiekhoogte)</p>";
    h += '<dl class="kv"><dt>Toegepaste norm</dt><dd>' + n.norm.map(function (q) { return "binnen " + q.straal_a + " m niet hoger dan de onderste wiekpunt" + (q.helling ? "; " + q.straal_a + "–" + q.tot + " m: + afstand × " + q.helling : "") + (q.beplanting ? "; ook beplanting" : ""); }).filter(function (v, i, x) { return x.indexOf(v) === i; }).map(esc).join(" | ") + "</dd>" +
      "<dt>Aangenomen wiekpunt</dt><dd>" + String(a.h_wiek_m).replace(".", ",") + " m (bereik " + String(a.bereik_m[0]).replace(".", ",") + "–" + String(a.bereik_m[1]).replace(".", ",") + " m), " + esc(a.bron) + "</dd>" +
      "<dt>Gebouwd na plandatum</dt><dd>" + n.waarvan_na_plandatum + " van de gebouwen boven de norm (de norm geldt voor nieuwbouw; bestaande gebouwen mogen er vaak overheen)</dd>" +
      (g.midden ? "<dt>Hoogste overschrijding</dt><dd>" + String(n.hoogste_overschrijding_m).replace(".", ",") + " m</dd>" : "") +
      (n.bomen_boven_norm_m2 ? "<dt>Bomen boven de norm</dt><dd>ongeveer " + n.bomen_boven_norm_m2.midden + " m² (indicatief)</dd>" : "") + "</dl>";
    return h + '<p class="note">Rode omlijning op de kaart: gebouw boven de norm bij de middenaanname (dik = ook bij ruime aanname). Hoogtes uit de AHN; de werkelijke wiekhoogte ontbreekt in de data.</p>';
  }

  var plantekst = null;

  function normHtml(q) {
    if (!q.regels_href) return "";
    var n = q.norm || {}, s = [];
    if (n.afstanden_m && n.afstanden_m.length) s.push("afstanden: " + n.afstanden_m.map(function (a) { return a[0] + (a[1] ? "–" + a[1] : "") + " m"; }).join(", "));
    if (n.helling) s.push("hoogtehelling " + n.helling + " van de afstand");
    if (n.referentie) s.push("vanaf de onderste punt van de wiek");
    if (n.beplanting_genoemd) s.push("ook beplanting genoemd");
    return '<details class="regels" data-h="' + esc(q.regels_href) + '"><summary>Regels uit het plan' + (s.length ? ": " + esc(s.join("; ")) : "") + '</summary><div class="regeltekst">Laden…</div></details>';
  }

  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.classList || !d.classList.contains("regels") || !d.open || d.dataset.geladen) return;
    d.dataset.geladen = "1";
    var vul = function () {
      var t = plantekst && plantekst[d.dataset.h];
      d.querySelector(".regeltekst").innerHTML = t ? "<p>" + esc(t.titel) + "</p><p>" + esc(t.tekst) + '</p><p class="note">Bron: API Ruimtelijke Plannen (Ruimtelijkeplannen.nl), opgehaald ' + esc(t.opgehaald) + ". Lees voor het juridische gezag altijd de plantekst zelf.</p>" : "Tekst niet beschikbaar.";
    };
    if (plantekst) return vul();
    fetch("data/plantekst.json").then(function (r) { return r.json(); }).then(function (j) { plantekst = j; vul(); }).catch(function () { d.querySelector(".regeltekst").textContent = "Tekst laden mislukt."; });
  }, true);

  function zoneOpKaart(m) {
    if (zoneLayer) { map.removeLayer(zoneLayer); zoneLayer = null; }
    if (normLayer) { map.removeLayer(normLayer); normLayer = null; }
    if (!m.zone || m.zone.status !== "Ja") return;
    if (m.norm && m.norm.gebouwen_boven_norm && m.norm.gebouwen_boven_norm.midden) {
      fetch("data/norm/" + m.nr + ".json").then(function (r) { return r.ok ? r.json() : null; }).then(function (g) {
        if (!g || selected !== m.nr) return;
        normLayer = L.geoJSON(g, {
          style: function (f) { return { color: "#D52B1E", weight: f.properties.robuust ? 4 : 2, fillColor: "#D52B1E", fillOpacity: 0.25 }; },
          onEachFeature: function (f, l) { var p = f.properties; l.bindTooltip("Boven de norm: +" + String(p.overschrijding).replace(".", ",") + " m, " + p.afstand + " m van de molen" + (p.bouwjaar ? ", bouwjaar " + p.bouwjaar : "") + (p.na_plandatum ? " (na plandatum)" : "")); }
        }).addTo(map);
      }).catch(function () {});
    }
    fetch("data/zone/" + m.nr + ".json").then(function (r) { return r.ok ? r.json() : null; }).then(function (g) {
      if (!g || selected !== m.nr) return;
      zoneLayer = L.geoJSON(g, {
        style: function (f) { return f.properties.soort === "biotoopzone" ? { color: "#01689B", weight: 2, dashArray: "6 4", fillColor: "#01689B", fillOpacity: 0.07 } : { color: "#475569", weight: 1, fill: false }; },
        onEachFeature: function (f, l) { l.bindTooltip(f.properties.naam + (f.properties.plan ? " (" + f.properties.plan + ", " + f.properties.datum + ")" : "")); }
      }).addTo(map);
      zoneLayer.bringToBack();
    }).catch(function () {});
  }

  function select(m, pan) {
    selected = m.nr;
    var r = m.row, b = m.biotoop || {};
    if (pan) { map.setView([m.lat, m.lon], Math.max(map.getZoom(), 14)); }
    document.querySelectorAll("#tabel tr.sel").forEach(function (t) { t.classList.remove("sel"); });
    var tr = document.querySelector('#tabel tr[data-nr="' + m.nr + '"]'); if (tr) tr.classList.add("sel");
    function kv(label, v) { return v === "" || v == null ? "" : "<dt>" + label + "</dt><dd>" + esc(v) + "</dd>"; }
    var adres = [r["Straat"], r["Huisnr."]].filter(Boolean).join(" ");
    var html = "<h3>" + esc(m.naam) + "</h3><p class=\"sub\">Rijksmonument " + m.nr + " · " + esc(adres) + (adres ? ", " : "") + esc(r["Postcode"]) + " " + esc(r["Plaats"]) + " · " + esc(r["Gemeente"]) + "</p>";
    if (m._cat === "Molen") {
      html += "<strong>Molenbiotoop</strong>" + (b.klasse ? rose(m) : '<p class="hint">Nog niet berekend.</p>');
      html += windHtml(m);
      html += zoneHtml(m);
      html += erfHtml(m);
    } else {
      html += '<p class="relnote"><span class="tag rel">Molengerelateerd</span> ' + esc(r["Functie volgens RCE-thesaurus (oorspronkelijk)"]) + ". Geen molen zelf, dus geen biotoop.</p>";
    }
    html += '<dl class="kv">' +
      kv("Jaar bouw", r["Jaar bouw"] ? r["Jaar bouw"] + (r["Herkomst jaar bouw"] ? " (" + r["Herkomst jaar bouw"] + ")" : "") : "") +
      kv("Type", val(r, "TYPE WINDMOLEN")) + kv("Plaatsing", val(r, "Plaatsing van de molen")) + kv("Functie", val(r, "Functie:")) +
      kv("Bouwkenmerken", val(r, "Bouwkenmerken")) + kv("Romptype", r["Romptype"]) + kv("Versieringen", r["Versieringen"]) +
      kv("Hoogte molen (AHN)", r["Hoogte molen (m, uit AHN)"] ? String(r["Hoogte molen (m, uit AHN)"]).replace(".", ",") + " m" : "") +
      kv("Bebouwd binnen 100 m", r["Bebouwd oppervlak binnen 100 m (aandeel)"] !== "" ? Math.round(r["Bebouwd oppervlak binnen 100 m (aandeel)"] * 100) + "%" : "") +
      kv("Boomkruinen binnen 100 m", r["Boomkruinen binnen 100 m (aandeel)"] !== "" ? Math.round(r["Boomkruinen binnen 100 m (aandeel)"] * 100) + "%" : "") +
      kv("Bebouwde kom", r["Bebouwde kom (RCE)"]) +
      kv("Beschermd gezicht", r["Binnen beschermd stads-/dorpsgezicht (Ja/Nee)"] === "Ja" ? r["Beschermd gezicht"] + " (" + r["Soort gezicht"] + ")" :
        (r["Afstand tot dichtstbijzijnd beschermd gezicht (m)"] !== "" ? "Nee, dichtstbij op " + r["Afstand tot dichtstbijzijnd beschermd gezicht (m)"] + " m" : "Nee")) +
      kv("Adres", r["Herkomst adres"]) + "</dl>";
    if (m.afbeeldingen && m.afbeeldingen.length) {
      html += '<strong>Afbeeldingen RCE</strong><div class="galerij">' + m.afbeeldingen.slice(0, 6).map(function (i) {
        return '<figure><a href="' + esc(i.pagina || i.commons || i.thumb) + '" target="_blank" rel="noopener"><img loading="lazy" src="' + esc(i.thumb) + '" alt="' + esc(i.titel) + '"></a><figcaption>' + esc(i.titel) + '<br>Foto: RCE · <a href="' + esc(i.licentie) + '" target="_blank" rel="noopener">CC BY 4.0</a></figcaption></figure>';
      }).join("") + "</div>" + (m.afbeeldingen.length > 6 ? '<p class="note">Nog ' + (m.afbeeldingen.length - 6) + ' afbeeldingen in de <a href="' + esc(m.afbeeldingen[0].pagina || "https://beeldbank.cultureelerfgoed.nl") + '" target="_blank" rel="noopener">RCE-beeldbank</a>.</p>' : "");
    }
    if (r["Omschrijving RCE"]) html += '<p class="omschr">' + esc(r["Omschrijving RCE"]) + "</p>";
    html += '<p class="links"><a href="' + esc(r["Monumentenregister"]) + '" target="_blank" rel="noopener">Monumentenregister</a><a href="' + esc(r["Linked data RCE"]) + '" target="_blank" rel="noopener">Linked data RCE</a>' + (r["Zoeklink Nederlandse Molendatabase"] ? '<a href="' + esc(r["Zoeklink Nederlandse Molendatabase"]) + '" target="_blank" rel="noopener">Zoeken in Nederlandse Molendatabase</a>' : "") + "</p>";
    document.getElementById("detail").innerHTML = html;
    erfOpKaart(m, pan);
    zoneOpKaart(m);
    if (markers[m.nr]) markers[m.nr].openTooltip();
  }

  function dekking() {
    var cols = data.kolommen, end = cols.indexOf(LAATSTE_TPL), tpl = cols.slice(0, end + 1), mrows = rows.filter(function (m) { return m._cat === "Molen"; }), n = mrows.length, out = "";
    var seen = {};
    tpl.forEach(function (c) {
      var short = c.split(":")[0].trim(), bron = "Niet in RCE/BAG/AHN; later aan te vullen (bv. Hollandsche Molen, SIM, eigenaar)";
      BRON.forEach(function (b) { if (c.indexOf(b[0]) === 0) bron = b[1]; });
      var g = mrows.filter(function (m) { var v = m.row[c]; return v !== "" && v != null && v !== "Naamloos"; }).length;
      var label = c.length > 60 ? c.split(":")[0].trim() : c;
      if (/^Molenbiotoop|^Erf|^Vang|^Wielen/.test(c)) label = c;
      out += "<tr><td>" + esc(label.trim()) + "</td><td>" + g + " / " + n + '</td><td><span class="barbg"><span class="bar" style="width:' + Math.round(120 * g / n) + 'px"></span></span></td><td>' + esc(bron) + "</td></tr>";
    });
    document.querySelector("#dekking tbody").innerHTML = out;
  }

  fetch("data/molens.json").then(function (r) { return r.json(); }).then(init).catch(function (e) {
    document.getElementById("telling").textContent = "Data laden mislukt: " + e;
  });
})();
