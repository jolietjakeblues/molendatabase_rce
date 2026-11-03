(function () {
  "use strict";
  var DIRS = ["N", "NO", "O", "ZO", "Z", "ZW", "W", "NW"];
  var DIRNAAM = { N: "noord", NO: "noordoost", O: "oost", ZO: "zuidoost", Z: "zuid", ZW: "zuidwest", W: "west", NW: "noordwest" };
  var KLEUR = { Goed: "#2b8a57", Matig: "#d19a1f", Slecht: "#c0392b", "": "#9aa3a6" };
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
  var LAATSTE_TPL = "Molenbiotoop: NW";

  var data, rows, filtered = [], map, layer, markers = {}, gezLayer, sortKey = "nr", sortDir = 1, selected = null, vink = {};

  function key(row, prefix) { for (var k in row) if (k.indexOf(prefix) === 0) return k; return null; }
  function val(row, prefix) { var k = key(row, prefix); return k ? row[k] : ""; }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }

  function overall(m) {
    var s = m.biotoop && m.biotoop.score;
    if (!s) return { klasse: "", gem: null };
    var v = DIRS.map(function (d) { return s[d]; }), g = v.reduce(function (a, b) { return a + b; }, 0) / v.length;
    return { klasse: g < 0.15 ? "Goed" : g < 0.45 ? "Matig" : "Slecht", gem: g };
  }

  function prep(m) {
    var r = m.row;
    m._o = overall(m);
    m._prov = r["Provincie"]; m._plaats = r["Plaats"]; m._gem = r["Gemeente"];
    m._type = val(r, "TYPE WINDMOLEN");
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
    document.getElementById("n-totaal").textContent = rows.length;
    document.getElementById("n2").textContent = rows.length;
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
    ["q", "f-provincie", "f-gemeente", "f-type", "f-gezicht", "f-bio"].forEach(function (id) {
      document.getElementById(id).addEventListener("input", apply);
    });
    document.getElementById("reset").addEventListener("click", function () {
      ["q", "f-provincie", "f-gemeente", "f-type", "f-gezicht", "f-bio"].forEach(function (id) { document.getElementById(id).value = ""; });
      apply();
    });
    document.getElementById("toggle-gezichten").addEventListener("change", function (e) {
      if (!gezLayer) return;
      if (e.target.checked) gezLayer.addTo(map); else map.removeLayer(gezLayer);
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
      p = document.getElementById("f-provincie").value, g = document.getElementById("f-gemeente").value, t = document.getElementById("f-type").value,
      z = document.getElementById("f-gezicht").value, b = document.getElementById("f-bio").value;
    filtered = rows.filter(function (m) {
      return (!q || m._zoek.indexOf(q) >= 0) && (!p || m._prov === p) && (!g || m._gem === g) && (!t || m._type === t) &&
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
      var c = KLEUR[m._o.klasse];
      var mk = L.circleMarker([m.lat, m.lon], { radius: 7, color: "#10181b", weight: 1, fillColor: c, fillOpacity: 0.92 });
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
      gezicht: function (m) { return m._gez; }, bio: function (m) { return m._o.gem == null ? 9 : m._o.gem; } }[sortKey];
    var list = filtered.slice().sort(function (a, b) { var x = f(a), y = f(b); return (x < y ? -1 : x > y ? 1 : 0) * sortDir; });
    var tb = document.querySelector("#tabel tbody");
    tb.innerHTML = list.map(function (m) {
      return '<tr data-nr="' + m.nr + '"' + (selected === m.nr ? ' class="sel"' : "") + '><td class="chk"><input type="checkbox" class="vink" aria-label="Selecteer ' + esc(m.naam) + '"' + (vink[m.nr] ? " checked" : "") + "></td><td>" + m.nr + "</td><td>" + esc(m.naam) + "</td><td>" + esc(m._plaats) + "</td><td>" + esc(m._gem) +
        "</td><td>" + (m._jaar || "") + "</td><td>" + esc(m._type) + "</td><td>" + esc(m._gez) + "</td><td>" +
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

  function rose(m) {
    var b = m.biotoop || {}, kl = b.klasse || {}, dom = b.dominant || {}, s = b.score || {};
    var cx = 85, cy = 85, R = 70, out = "";
    DIRS.forEach(function (d, i) {
      var a0 = (i * 45 - 22.5 - 90) * Math.PI / 180, a1 = (i * 45 + 22.5 - 90) * Math.PI / 180;
      var x0 = cx + R * Math.cos(a0), y0 = cy + R * Math.sin(a0), x1 = cx + R * Math.cos(a1), y1 = cy + R * Math.sin(a1);
      var c = KLEUR[kl[d] || ""];
      var o = dom[d] ? dom[d].type + " van " + String(dom[d].hoogte).replace(".", ",") + " m op " + dom[d].afstand + " m" : "geen obstakel dat telt";
      out += '<path d="M' + cx + " " + cy + " L" + x0.toFixed(1) + " " + y0.toFixed(1) + " A" + R + " " + R + " 0 0 1 " + x1.toFixed(1) + " " + y1.toFixed(1) + ' Z" fill="' + c + '" stroke="var(--paper)" stroke-width="2"><title>Wind uit ' + DIRNAAM[d] + ": " + (kl[d] || "onbekend") + " (" + (s[d] != null ? s[d].toFixed(2) : "-") + "). Zwaarste obstakel: " + o + "</title></path>";
      var lx = cx + (R + 11) * Math.cos((i * 45 - 90) * Math.PI / 180), ly = cy + (R + 11) * Math.sin((i * 45 - 90) * Math.PI / 180);
      out += '<text x="' + lx.toFixed(1) + '" y="' + (ly + 3.5).toFixed(1) + '" text-anchor="middle" font-size="10" fill="currentColor">' + d + "</text>";
    });
    out += '<circle cx="' + cx + '" cy="' + cy + '" r="6" fill="var(--paper)" stroke="currentColor"/>';
    var lijst = DIRS.map(function (d) {
      return "<li><strong>" + d + "</strong> " + (kl[d] ? '<span class="tag ' + kl[d] + '">' + kl[d] + "</span>" : "–") +
        (dom[d] ? " " + dom[d].type + " " + String(dom[d].hoogte).replace(".", ",") + " m op " + dom[d].afstand + " m" : "") + "</li>";
    }).join("");
    return '<div class="rose"><svg viewBox="0 0 170 170" role="img" aria-label="Molenbiotoop per windrichting">' + out + "</svg><ul>" + lijst + "</ul></div>";
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
    html += "<strong>Molenbiotoop</strong>" + (b.klasse ? rose(m) : '<p class="hint">Nog niet berekend.</p>');
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
    if (markers[m.nr]) markers[m.nr].openTooltip();
  }

  function dekking() {
    var cols = data.kolommen, end = cols.indexOf(LAATSTE_TPL), tpl = cols.slice(0, end + 1), n = rows.length, out = "";
    var seen = {};
    tpl.forEach(function (c) {
      var short = c.split(":")[0].trim(), bron = "Niet in RCE/BAG/AHN; later aan te vullen (bv. Hollandsche Molen, SIM, eigenaar)";
      BRON.forEach(function (b) { if (c.indexOf(b[0]) === 0) bron = b[1]; });
      var g = rows.filter(function (m) { var v = m.row[c]; return v !== "" && v != null && v !== "Naamloos"; }).length;
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
