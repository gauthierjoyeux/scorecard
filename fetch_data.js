// ── Bigblue Scorecard — Metabase data fetcher ─────────────────────────────────
// Paste this into the Chrome DevTools console on any Metabase page.
// It fetches all 6 scorecard queries and downloads scorecard_data.json.

(function () {
  const questions = [
    { id: 26473, name: "B2C Pack UPH",      wh_col: "warehouse_id",          date_col: "week_start",      color: true  },
    { id: 26435, name: "B2C NAC",           wh_col: "warehouse_id",          date_col: "preparation_day", color: false },
    { id: 26434, name: "B2C Pick UPH",      wh_col: "warehouse_id",          date_col: "preparation_day", color: true  },
    { id: 26470, name: "Ship UPH",          wh_col: "warehouse_external_id", date_col: "ship_time",        color: true  },
    { id: 26471, name: "Inbound (Receive)", wh_col: "warehouse_external_id", date_col: "create_time",      color: true  },
    { id: 26472, name: "Replenishments",    wh_col: "warehouse_external_id", date_col: "update_time",      color: true  },
  ];

  console.log("⏳ Fetching scorecard data from Metabase...");

  Promise.all(questions.map(q =>
    fetch("/api/card/pivot/" + q.id + "/query", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ignore_cache: true}),
    })
      .then(r => r.json())
      .then(d => ({
        id: q.id, name: q.name, wh_col: q.wh_col,
        date_col: q.date_col, color: q.color,
        cols: d.data.cols.map(c => c.name),
        rows: d.data.rows,
      }))
  )).then(results => {
    const blob = new Blob([JSON.stringify(results)], { type: "application/json" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = "scorecard_data.json";
    a.click();
    URL.revokeObjectURL(url);
    console.log("✅ scorecard_data.json downloaded — now run ./update.sh");
  }).catch(err => console.error("❌ Error:", err));
})();
