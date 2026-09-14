(() => {
  "use strict";

  const state = {
    guildId: null,
    graphData: null,
    graphMode: "combined",
    graphThreshold: 300,
    graphSearch: "",
    selectedGame: null,
    wrappedControlsLoaded: false,
  };

  // ---------- small helpers ----------

  function formatDuration(seconds) {
    if (!seconds || seconds <= 0) return "0m";
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    if (days > 0) return `${days}d ${hours}h`;
    if (hours > 0) return `${hours}h ${mins}m`;
    return `${mins}m`;
  }

  function formatDate(unixSeconds) {
    if (!unixSeconds) return "—";
    return new Date(unixSeconds * 1000).toLocaleDateString(undefined, {
      year: "numeric", month: "short", day: "numeric",
    });
  }

  async function api(path, params) {
    const url = new URL(path, window.location.origin);
    if (params) {
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null) url.searchParams.set(k, v);
      }
    }
    if (state.guildId) url.searchParams.set("guild_id", state.guildId);
    showLoading(true);
    try {
      const res = await fetch(url);
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `${res.status} ${res.statusText}`);
      }
      return await res.json();
    } catch (err) {
      showError(err.message || String(err));
      throw err;
    } finally {
      showLoading(false);
    }
  }

  function showLoading(on) {
    document.getElementById("loading-banner").hidden = !on;
  }

  let errorTimer = null;
  function showError(msg) {
    const el = document.getElementById("error-banner");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(errorTimer);
    errorTimer = setTimeout(() => { el.hidden = true; }, 6000);
  }

  function el(tag, attrs = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") node.textContent = v;
      else if (k === "class") node.className = v;
      else node.setAttribute(k, v);
    }
    for (const c of [].concat(children)) node.appendChild(c);
    return node;
  }

  function buildTable(headers, rows, rowRenderer) {
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const trh = document.createElement("tr");
    headers.forEach((h) => trh.appendChild(el("th", { text: h })));
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    rows.forEach((row) => tbody.appendChild(rowRenderer(row)));
    table.appendChild(tbody);
    return table;
  }

  function leaderboardTable(rows) {
    return buildTable(["#", "Name", "Time"], rows, (r) => {
      const tr = el("tr");
      tr.appendChild(el("td", { class: "rank-cell", text: r.rank }));
      tr.appendChild(el("td", { text: r.name }));
      tr.appendChild(el("td", { class: "num-cell", text: formatDuration(r.seconds) }));
      return tr;
    });
  }

  // ---------- tabs ----------

  function initTabs() {
    document.getElementById("tabs").addEventListener("click", (e) => {
      const btn = e.target.closest(".tab-btn");
      if (!btn) return;
      document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      document.getElementById(`tab-${btn.dataset.tab}`).classList.add("active");
      if (btn.dataset.tab === "graph" && !state.graphData) loadGraph();
      if (btn.dataset.tab === "games" && timelineData) renderTimeline();
      if (btn.dataset.tab === "wrapped" && !state.wrappedControlsLoaded) {
        state.wrappedControlsLoaded = true;
        initWrappedControls();
      }
    });
  }

  // ---------- guild selection ----------

  async function initGuilds() {
    const data = await api("/api/guilds");
    const select = document.getElementById("guild-select");
    if (data.guilds.length <= 1) {
      state.guildId = data.guilds[0] ? data.guilds[0].id : null;
      return;
    }
    select.hidden = false;
    data.guilds.forEach((g) => select.appendChild(el("option", { value: g.id, text: g.name })));
    state.guildId = data.guilds[0].id;
    select.value = state.guildId;
    select.addEventListener("change", () => {
      state.guildId = select.value;
      state.graphData = null;
      loadOverview();
      loadLeaderboards();
      loadGames();
      loadTimeline();
      if (document.getElementById("tab-graph").classList.contains("active")) loadGraph();
    });
  }

  // ---------- overview ----------

  async function loadOverview() {
    const ov = await api("/api/overview");
    document.getElementById("guild-range").textContent =
      ov.first_seen ? `Logging since ${formatDate(ov.first_seen)}` : "";

    const tiles = [
      { label: "Voice time logged", value: formatDuration(ov.voice_seconds), sub: `${ov.voice_channels} channels` },
      { label: "Game time logged", value: formatDuration(ov.game_seconds), sub: `${ov.game_count} games` },
      { label: "People seen", value: ov.unique_users, sub: `${ov.voice_users} in voice, ${ov.game_users} gaming` },
    ];
    const grid = document.getElementById("stat-tiles");
    grid.innerHTML = "";
    tiles.forEach((t) => {
      grid.appendChild(el("div", { class: "stat-tile" }, [
        el("div", { class: "stat-label", text: t.label }),
        el("div", { class: "stat-value", text: String(t.value) }),
        el("div", { class: "stat-sub", text: t.sub }),
      ]));
    });

    const [lb, vlb] = await Promise.all([
      api("/api/leaderboard", { limit: 5 }),
      api("/api/voice/leaderboard", { limit: 5 }),
    ]);
    const lbEl = document.getElementById("overview-leaderboard");
    lbEl.innerHTML = "";
    lbEl.appendChild(leaderboardTable(lb.leaderboard));
    const vlbEl = document.getElementById("overview-voice");
    vlbEl.innerHTML = "";
    vlbEl.appendChild(leaderboardTable(vlb.leaderboard));
  }

  // ---------- leaderboards tab ----------

  async function loadLeaderboards() {
    const [lb, vlb, channels] = await Promise.all([
      api("/api/leaderboard", { limit: 25 }),
      api("/api/voice/leaderboard", { limit: 25 }),
      api("/api/voice/channels"),
    ]);
    const lbEl = document.getElementById("leaderboard-games");
    lbEl.innerHTML = "";
    lbEl.appendChild(leaderboardTable(lb.leaderboard));

    const vlbEl = document.getElementById("leaderboard-voice");
    vlbEl.innerHTML = "";
    vlbEl.appendChild(leaderboardTable(vlb.leaderboard));

    const chEl = document.getElementById("leaderboard-channels");
    chEl.innerHTML = "";
    chEl.appendChild(buildTable(["Channel", "Time", "People"], channels.channels, (c) => {
      const tr = el("tr");
      tr.appendChild(el("td", { text: c.name }));
      tr.appendChild(el("td", { class: "num-cell", text: formatDuration(c.seconds) }));
      tr.appendChild(el("td", { class: "num-cell", text: c.users }));
      return tr;
    }));
  }

  // ---------- games tab ----------

  async function loadGames() {
    const data = await api("/api/games");
    const listEl = document.getElementById("games-list");
    listEl.innerHTML = "";
    const table = buildTable(["Game", "Time", "Players"], data.games, (g) => {
      const tr = el("tr", { class: "clickable game-row" });
      if (g.game === state.selectedGame) tr.classList.add("selected");
      tr.appendChild(el("td", { text: g.game }));
      tr.appendChild(el("td", { class: "num-cell", text: formatDuration(g.seconds) }));
      tr.appendChild(el("td", { class: "num-cell", text: g.players }));
      tr.addEventListener("click", () => {
        state.selectedGame = g.game;
        loadGameTop10(g.game);
        listEl.querySelectorAll(".game-row").forEach((r) => r.classList.remove("selected"));
        tr.classList.add("selected");
      });
      return tr;
    });
    listEl.appendChild(table);

    if (data.games.length) {
      const first = state.selectedGame && data.games.some((g) => g.game === state.selectedGame)
        ? state.selectedGame : data.games[0].game;
      state.selectedGame = first;
      await loadGameTop10(first);
      listEl.querySelectorAll(".game-row").forEach((r) => {
        if (r.firstChild.textContent === first) r.classList.add("selected");
      });
    }
  }

  async function loadGameTop10(game) {
    document.getElementById("games-top10-title").textContent = `Top 10 — ${game}`;
    const data = await api(`/api/games/${encodeURIComponent(game)}/top10`);
    const el2 = document.getElementById("games-top10");
    el2.innerHTML = "";
    el2.appendChild(leaderboardTable(data.top10));
  }

  // ---------- game popularity timeline ----------

  const TIMELINE_COLORS = [
    "var(--cat-1)", "var(--cat-2)", "var(--cat-3)", "var(--cat-4)",
    "var(--cat-5)", "var(--cat-6)", "var(--cat-7)",
  ];

  function timelineColor(game, games) {
    if (game === "Other") return "var(--cat-other)";
    return TIMELINE_COLORS[games.indexOf(game) % TIMELINE_COLORS.length];
  }

  function parseMonth(ym) {
    const [y, m] = ym.split("-").map(Number);
    return new Date(Date.UTC(y, m - 1, 1));
  }

  let timelineData = null;

  async function loadTimeline() {
    timelineData = await api("/api/games/timeline");
    renderTimeline();
  }

  function renderTimeline() {
    const wrap = document.querySelector(".timeline-wrap");
    const empty = document.getElementById("timeline-empty");
    const legend = document.getElementById("timeline-legend");
    legend.innerHTML = "";

    if (!timelineData || timelineData.months.length < 2) {
      empty.hidden = false;
      d3.select("#timeline-svg").selectAll("*").remove();
      return;
    }
    empty.hidden = true;

    const { games, months } = timelineData;
    games.forEach((game) => {
      legend.appendChild(el("div", { class: "legend-item" }, [
        el("span", { class: "legend-swatch", style: `background:${timelineColor(game, games)}` }),
        el("span", { text: game }),
      ]));
    });

    const width = wrap.clientWidth;
    const height = wrap.clientHeight;
    const margin = { top: 12, right: 16, bottom: 24, left: 44 };
    const dates = months.map((m) => parseMonth(m.month));

    const svg = d3.select("#timeline-svg").attr("viewBox", [0, 0, width, height]);
    svg.selectAll("*").remove();

    const x = d3.scaleUtc().domain(d3.extent(dates)).range([margin.left, width - margin.right]);
    const y = d3.scaleLinear().domain([0, 1]).range([height - margin.bottom, margin.top]);

    const stacked = d3.stack().keys(games).offset(d3.stackOffsetExpand)(months);
    const area = d3.area()
      .x((d, i) => x(dates[i]))
      .y0((d) => y(d[0]))
      .y1((d) => y(d[1]))
      .curve(d3.curveMonotoneX);

    svg.append("g")
      .selectAll("path")
      .data(stacked)
      .join("path")
      .attr("fill", (d) => timelineColor(d.key, games))
      .attr("stroke", "var(--surface)")
      .attr("stroke-width", 2)
      .attr("d", area);

    const tickCount = Math.max(2, Math.min(months.length, Math.floor(width / 90)));
    svg.append("g")
      .attr("class", "timeline-axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(d3.axisBottom(x).ticks(tickCount).tickFormat(d3.utcFormat("%b %Y")).tickSizeOuter(0));

    svg.append("g")
      .attr("class", "timeline-axis")
      .attr("transform", `translate(${margin.left},0)`)
      .call(d3.axisLeft(y).ticks(4).tickFormat(d3.format(".0%")).tickSizeOuter(0))
      .call((g) => g.select(".domain").remove());

    const crosshair = svg.append("line")
      .attr("class", "timeline-crosshair")
      .attr("y1", margin.top)
      .attr("y2", height - margin.bottom)
      .style("opacity", 0);

    const tooltip = document.getElementById("timeline-tooltip");

    function showTooltip(idx, pointerX, pointerY) {
      const month = months[idx];
      const rows = games
        .map((game) => ({ game, seconds: month[game] || 0 }))
        .filter((r) => r.seconds > 0)
        .sort((a, b) => b.seconds - a.seconds);

      tooltip.innerHTML = "";
      tooltip.appendChild(el("div", { class: "tt-title", text: month.label }));
      tooltip.appendChild(el("div", { class: "tt-line", text: `Total: ${formatDuration(month.total_seconds)}` }));
      rows.forEach((r) => {
        const pct = Math.round((r.seconds / month.total_seconds) * 100);
        tooltip.appendChild(el("div", { class: "tt-row" }, [
          el("span", { class: "tt-key", style: `background:${timelineColor(r.game, games)}` }),
          el("span", { class: "tt-value", text: `${pct}%` }),
          el("span", { class: "tt-series", text: ` ${r.game} · ${formatDuration(r.seconds)}` }),
        ]));
      });
      tooltip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      tooltip.style.left = Math.min(pointerX + 14, rect.width - tooltip.offsetWidth - 8) + "px";
      tooltip.style.top = Math.min(pointerY + 14, rect.height - tooltip.offsetHeight - 8) + "px";
    }

    svg.append("rect")
      .attr("x", margin.left)
      .attr("y", margin.top)
      .attr("width", Math.max(0, width - margin.left - margin.right))
      .attr("height", Math.max(0, height - margin.top - margin.bottom))
      .attr("fill", "transparent")
      .on("mousemove", (event) => {
        const [px] = d3.pointer(event);
        const t = x.invert(px);
        let idx = d3.bisector((d) => d).left(dates, t);
        idx = Math.max(0, Math.min(dates.length - 1, idx));
        if (idx > 0 && Math.abs(dates[idx - 1] - t) < Math.abs(dates[idx] - t)) idx -= 1;
        crosshair.attr("x1", x(dates[idx])).attr("x2", x(dates[idx])).style("opacity", 1);
        const rect = wrap.getBoundingClientRect();
        showTooltip(idx, event.clientX - rect.left, event.clientY - rect.top);
      })
      .on("mouseleave", () => {
        crosshair.style("opacity", 0);
        tooltip.hidden = true;
      });
  }

  window.addEventListener("resize", () => {
    if (document.getElementById("tab-games").classList.contains("active")) renderTimeline();
  });

  // ---------- relationship graph ----------

  const graph = {
    svg: null, gLayer: null, simulation: null,
    nodeSel: null, linkSel: null, labelSel: null,
    width: 0, height: 0,
    neighborMap: new Map(),
  };

  function seriesColor(v, g) {
    const hasV = v > 0, hasG = g > 0;
    if (hasV && hasG) return "var(--series-both)";
    if (hasV) return "var(--series-voice)";
    return "var(--series-game)";
  }

  function edgeWeight(d) {
    if (state.graphMode === "voice") return d.voice_seconds;
    if (state.graphMode === "games") return d.game_seconds;
    return d.voice_seconds + d.game_seconds;
  }

  function edgeColor(d) {
    if (state.graphMode === "voice") return "var(--series-voice)";
    if (state.graphMode === "games") return "var(--series-game)";
    return seriesColor(d.voice_seconds, d.game_seconds);
  }

  function nodeValue(d) {
    return d.voice_seconds + d.game_seconds;
  }

  function updateLegend() {
    const legend = document.getElementById("graph-legend");
    legend.innerHTML = "";
    const items = state.graphMode === "voice"
      ? [["Voice together", "var(--series-voice)"]]
      : state.graphMode === "games"
      ? [["Games together", "var(--series-game)"]]
      : [
          ["Voice only", "var(--series-voice)"],
          ["Games only", "var(--series-game)"],
          ["Both", "var(--series-both)"],
        ];
    items.forEach(([label, color]) => {
      legend.appendChild(el("div", { class: "legend-item" }, [
        el("span", { class: "legend-swatch", style: `background:${color}` }),
        el("span", { text: label }),
      ]));
    });
  }

  async function loadGraph() {
    const data = await api("/api/graph", { min_seconds: 0 });
    state.graphData = data;
    renderGraph();
  }

  function renderGraph() {
    if (!state.graphData) return;
    updateLegend();

    const wrap = document.querySelector(".graph-wrap");
    graph.width = wrap.clientWidth;
    graph.height = wrap.clientHeight;

    const threshold = state.graphThreshold;
    const q = state.graphSearch.trim().toLowerCase();

    const edges = state.graphData.edges.filter((e) => {
      if (state.graphMode === "voice" && e.voice_seconds <= 0) return false;
      if (state.graphMode === "games" && e.game_seconds <= 0) return false;
      return edgeWeight(e) >= threshold;
    });

    const connected = new Set();
    edges.forEach((e) => { connected.add(e.source); connected.add(e.target); });
    const nodes = state.graphData.nodes
      .filter((n) => connected.has(n.id))
      .map((n) => ({ ...n }));

    document.getElementById("graph-empty").hidden = nodes.length > 0;
    if (!nodes.length) {
      if (graph.gLayer) graph.gLayer.selectAll("*").remove();
      return;
    }

    graph.neighborMap = new Map(nodes.map((n) => [n.id, new Set()]));
    const links = edges.map((e) => ({ ...e }));
    links.forEach((l) => {
      graph.neighborMap.get(l.source)?.add(l.target);
      graph.neighborMap.get(l.target)?.add(l.source);
    });

    const maxVal = d3.max(nodes, nodeValue) || 1;
    const radiusScale = d3.scaleSqrt().domain([0, maxVal]).range([7, 28]);
    const colorScale = d3.scaleSqrt().domain([0, maxVal])
      .range(["#1c5cab", "#cde2fb"]);

    const maxW = d3.max(links, edgeWeight) || 1;
    const widthScale = d3.scaleSqrt().domain([0, maxW]).range([1, 8]);

    const svg = d3.select("#graph-svg").attr("viewBox", [0, 0, graph.width, graph.height]);
    svg.selectAll("*").remove();

    const zoomLayer = svg.append("g");
    svg.call(d3.zoom().scaleExtent([0.2, 4]).on("zoom", (event) => {
      zoomLayer.attr("transform", event.transform);
    }));

    graph.gLayer = zoomLayer;

    const link = zoomLayer.append("g").attr("stroke-opacity", 0.55)
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", edgeColor)
      .attr("stroke-width", (d) => widthScale(edgeWeight(d)));

    const nodeGroup = zoomLayer.append("g")
      .selectAll("g")
      .data(nodes, (d) => d.id)
      .join("g")
      .attr("class", "graph-node")
      .call(drag());

    const circle = nodeGroup.append("circle")
      .attr("r", (d) => radiusScale(nodeValue(d)))
      .attr("fill", (d) => colorScale(nodeValue(d)))
      .attr("stroke", "rgba(255,255,255,0.25)")
      .attr("stroke-width", 1.5);

    const label = nodeGroup.append("text")
      .text((d) => d.name)
      .attr("dy", (d) => radiusScale(nodeValue(d)) + 13)
      .attr("text-anchor", "middle")
      .attr("fill", "var(--text-secondary)")
      .attr("font-size", 11)
      .attr("pointer-events", "none");

    graph.nodeSel = nodeGroup;
    graph.linkSel = link;
    graph.labelSel = label;

    const matched = q
      ? new Set(nodes.filter((n) => n.name.toLowerCase().includes(q)).map((n) => n.id))
      : null;

    function applyHighlight(focusId) {
      const highlightSet = focusId
        ? new Set([focusId, ...graph.neighborMap.get(focusId)])
        : matched;
      circle.attr("opacity", (d) => !highlightSet || highlightSet.has(d.id) ? 1 : 0.15);
      label.attr("opacity", (d) => !highlightSet || highlightSet.has(d.id) ? 1 : 0.15);
      link.attr("opacity", (d) => {
        if (!highlightSet) return 0.55;
        const on = highlightSet.has(d.source.id ?? d.source) && highlightSet.has(d.target.id ?? d.target);
        return on ? 0.9 : 0.05;
      });
    }
    applyHighlight(null);

    const tooltip = document.getElementById("graph-tooltip");
    function showTooltip(html, x, y) {
      tooltip.innerHTML = html;
      tooltip.hidden = false;
      const wrapRect = wrap.getBoundingClientRect();
      tooltip.style.left = Math.min(x + 14, wrapRect.width - 250) + "px";
      tooltip.style.top = Math.min(y + 14, wrapRect.height - 100) + "px";
    }
    function hideTooltip() { tooltip.hidden = true; }

    nodeGroup
      .on("mouseenter", (event, d) => {
        applyHighlight(d.id);
        const rect = wrap.getBoundingClientRect();
        showTooltip(
          `<div class="tt-title">${d.name}</div>` +
          `<div class="tt-line">Voice: ${formatDuration(d.voice_seconds)}</div>` +
          `<div class="tt-line">Games: ${formatDuration(d.game_seconds)}</div>` +
          (d.top_game ? `<div class="tt-line">Most played: ${d.top_game}</div>` : ""),
          event.clientX - rect.left, event.clientY - rect.top
        );
      })
      .on("mousemove", (event) => {
        const rect = wrap.getBoundingClientRect();
        tooltip.style.left = Math.min(event.clientX - rect.left + 14, rect.width - 250) + "px";
        tooltip.style.top = Math.min(event.clientY - rect.top + 14, rect.height - 100) + "px";
      })
      .on("mouseleave", () => { applyHighlight(null); hideTooltip(); });

    link
      .on("mouseenter", (event, d) => {
        const rect = wrap.getBoundingClientRect();
        const channelLines = (d.top_channels || [])
          .map((c) => `<div class="tt-line">${c.name}: ${formatDuration(c.seconds)}</div>`).join("");
        const gameLines = (d.top_games || [])
          .map((g) => `<div class="tt-line">${g.game}: ${formatDuration(g.seconds)}</div>`).join("");
        showTooltip(
          `<div class="tt-title">${d.source.name || d.source}  &harr;  ${d.target.name || d.target}</div>` +
          `<div class="tt-line">Voice together: ${formatDuration(d.voice_seconds)}</div>` +
          channelLines +
          `<div class="tt-line">Gaming together: ${formatDuration(d.game_seconds)}</div>` +
          gameLines,
          event.clientX - rect.left, event.clientY - rect.top
        );
      })
      .on("mousemove", (event) => {
        const rect = wrap.getBoundingClientRect();
        tooltip.style.left = Math.min(event.clientX - rect.left + 14, rect.width - 250) + "px";
        tooltip.style.top = Math.min(event.clientY - rect.top + 14, rect.height - 100) + "px";
      })
      .on("mouseleave", hideTooltip);

    const simulation = d3.forceSimulation(nodes)
      .force("link", d3.forceLink(links).id((d) => d.id).distance((d) => 90 + 70 / Math.max(1, Math.sqrt(edgeWeight(d) / 600))).strength(0.25))
      .force("charge", d3.forceManyBody().strength(-520))
      .force("center", d3.forceCenter(graph.width / 2, graph.height / 2))
      .force("collision", d3.forceCollide().radius((d) => radiusScale(nodeValue(d)) + 16))
      .on("tick", () => {
        link
          .attr("x1", (d) => d.source.x).attr("y1", (d) => d.source.y)
          .attr("x2", (d) => d.target.x).attr("y2", (d) => d.target.y);
        nodeGroup.attr("transform", (d) => `translate(${d.x},${d.y})`);
      });

    graph.simulation = simulation;

    if (matched && matched.size) {
      // Nudge matched nodes toward the visual foreground on load.
      setTimeout(() => applyHighlight(null), 400);
    }

    function drag() {
      return d3.drag()
        .on("start", (event, d) => {
          if (!event.active) simulation.alphaTarget(0.3).restart();
          d.fx = d.x; d.fy = d.y;
        })
        .on("drag", (event, d) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d) => {
          if (!event.active) simulation.alphaTarget(0);
          d.fx = null; d.fy = null;
        });
    }
  }

  function initGraphControls() {
    document.getElementById("graph-mode").addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-btn");
      if (!btn) return;
      document.querySelectorAll("#graph-mode .seg-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.graphMode = btn.dataset.mode;
      renderGraph();
    });

    const thresholdInput = document.getElementById("graph-threshold");
    const thresholdValue = document.getElementById("graph-threshold-value");
    const updateThresholdLabel = () => { thresholdValue.textContent = formatDuration(state.graphThreshold); };
    state.graphThreshold = Number(thresholdInput.value);
    updateThresholdLabel();
    thresholdInput.addEventListener("input", () => {
      state.graphThreshold = Number(thresholdInput.value);
      updateThresholdLabel();
      renderGraph();
    });

    let searchTimer = null;
    document.getElementById("graph-search").addEventListener("input", (e) => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => {
        state.graphSearch = e.target.value;
        renderGraph();
      }, 150);
    });

    window.addEventListener("resize", () => {
      if (document.getElementById("tab-graph").classList.contains("active")) renderGraph();
    });
  }

  // ---------- your year ----------

  async function initWrappedControls() {
    const userSelect = document.getElementById("wrapped-user");
    const yearSelect = document.getElementById("wrapped-year");

    const [usersData, yearsData] = await Promise.all([api("/api/users"), api("/api/years")]);

    usersData.users.forEach((u) => userSelect.appendChild(el("option", { value: u.id, text: u.name })));
    yearsData.years.forEach((y) => yearSelect.appendChild(el("option", { value: y, text: y })));
    if (yearsData.years.length) yearSelect.value = yearsData.years[0];

    userSelect.addEventListener("change", loadWrapped);
    yearSelect.addEventListener("change", loadWrapped);

    const empty = document.getElementById("wrapped-empty");
    empty.textContent = "Pick a person to see their recap.";
    empty.hidden = false;
  }

  async function loadWrapped() {
    const userSelect = document.getElementById("wrapped-user");
    const yearSelect = document.getElementById("wrapped-year");
    const userId = userSelect.value;
    const year = yearSelect.value;
    const content = document.getElementById("wrapped-content");
    const empty = document.getElementById("wrapped-empty");
    content.innerHTML = "";
    empty.hidden = true;

    if (!userId || !year) {
      empty.textContent = "Pick a person to see their recap.";
      empty.hidden = false;
      return;
    }

    const url = new URL("/api/wrapped", window.location.origin);
    url.searchParams.set("user_id", userId);
    url.searchParams.set("year", year);
    if (state.guildId) url.searchParams.set("guild_id", state.guildId);

    showLoading(true);
    try {
      const res = await fetch(url);
      if (res.status === 404) {
        const personName = userSelect.selectedOptions[0] ? userSelect.selectedOptions[0].textContent : "this person";
        empty.textContent = `No activity logged for ${personName} in ${year}.`;
        empty.hidden = false;
        return;
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `${res.status} ${res.statusText}`);
      }
      renderWrapped(await res.json());
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      showLoading(false);
    }
  }

  function renderWrapped(data) {
    const content = document.getElementById("wrapped-content");
    content.innerHTML = "";
    document.getElementById("wrapped-empty").hidden = true;

    const totalSeconds = data.voice_seconds + data.game_seconds;

    content.appendChild(el("div", { class: "wrapped-hero" }, [
      el("div", { class: "wrapped-kicker", text: `${data.year} Year in Review` }),
      el("h2", { text: data.user.name }),
      el("div", {
        class: "wrapped-hero-sub",
        text: `Active on ${data.active_days} day${data.active_days === 1 ? "" : "s"} this year`,
      }),
      el("div", { class: "wrapped-hero-figure" }, [
        document.createTextNode(formatDuration(totalSeconds)),
        el("span", { class: "unit", text: "in voice & games combined" }),
      ]),
    ]));

    const tiles = [
      {
        label: "Voice time",
        value: formatDuration(data.voice_seconds),
        sub: data.voice_rank ? `#${data.voice_rank.rank} of ${data.voice_rank.of} on the server` : "No voice activity",
      },
      {
        label: "Game time",
        value: formatDuration(data.game_seconds),
        sub: data.game_rank ? `#${data.game_rank.rank} of ${data.game_rank.of} on the server` : "No game activity",
      },
    ];
    if (data.busiest_month) {
      tiles.push({ label: "Busiest month", value: data.busiest_month.name, sub: formatDuration(data.busiest_month.seconds) });
    }
    if (data.top_voice_channel) {
      tiles.push({ label: "Favorite channel", value: data.top_voice_channel.name, sub: formatDuration(data.top_voice_channel.seconds) });
    }
    const grid = el("div", { class: "wrapped-grid" });
    tiles.forEach((t) => {
      grid.appendChild(el("div", { class: "stat-tile" }, [
        el("div", { class: "stat-label", text: t.label }),
        el("div", { class: "stat-value", text: String(t.value) }),
        el("div", { class: "stat-sub", text: t.sub }),
      ]));
    });
    content.appendChild(grid);

    if (data.top_voice_partner || data.top_game_partner) {
      const partners = el("div", { class: "wrapped-partners" });
      if (data.top_voice_partner) {
        partners.appendChild(el("div", { class: "partner-card" }, [
          el("div", { class: "partner-label", text: "Chatted with most" }),
          el("div", { class: "partner-name", text: data.top_voice_partner.name }),
          el("div", { class: "partner-time", text: `${formatDuration(data.top_voice_partner.seconds)} together in voice` }),
        ]));
      }
      if (data.top_game_partner) {
        const gamesLine = data.top_game_partner.top_games.map((g) => g.game).join(", ");
        const card = el("div", { class: "partner-card game-partner" }, [
          el("div", { class: "partner-label", text: "Played with most" }),
          el("div", { class: "partner-name", text: data.top_game_partner.name }),
          el("div", { class: "partner-time", text: `${formatDuration(data.top_game_partner.seconds)} playing together` }),
        ]);
        if (gamesLine) card.appendChild(el("div", { class: "partner-games", text: `Mostly: ${gamesLine}` }));
        partners.appendChild(card);
      }
      content.appendChild(partners);
    }

    if (data.top_games.length) {
      const maxSeconds = data.top_games[0].seconds || 1;
      const barList = el("div", { class: "bar-list" });
      data.top_games.forEach((g, i) => {
        barList.appendChild(el("div", { class: "bar-row" }, [
          el("span", { class: "bar-rank", text: String(i + 1) }),
          el("span", { class: "bar-label", text: g.game }),
          el("div", { class: "bar-track" }, [
            el("div", { class: "bar-fill", style: `width:${Math.max(4, (g.seconds / maxSeconds) * 100)}%` }),
          ]),
          el("span", { class: "bar-value", text: formatDuration(g.seconds) }),
        ]));
      });
      content.appendChild(el("div", { class: "panel" }, [
        el("h2", { text: "Top games this year" }),
        barList,
      ]));
    }

    const longestLines = [];
    if (data.longest_voice_session) {
      const s = data.longest_voice_session;
      longestLines.push(`Longest voice session: ${formatDuration(s.seconds)} in ${s.channel} on ${formatDate(s.date)}`);
    }
    if (data.longest_game_session) {
      const s = data.longest_game_session;
      longestLines.push(`Longest game session: ${formatDuration(s.seconds)} playing ${s.game} on ${formatDate(s.date)}`);
    }
    if (longestLines.length) {
      const panel = el("div", { class: "panel" }, [el("h2", { text: "Longest sessions" })]);
      longestLines.forEach((line) => panel.appendChild(el("div", { class: "stat-sub", text: line })));
      content.appendChild(panel);
    }
  }

  // ---------- boot ----------

  async function main() {
    initTabs();
    initGraphControls();
    try {
      await initGuilds();
      await loadOverview();
      await loadLeaderboards();
      await loadGames();
      await loadTimeline();
    } catch (err) {
      // already surfaced via showError
      console.error(err);
    }
  }

  document.addEventListener("DOMContentLoaded", main);
})();
