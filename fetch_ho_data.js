// ── Bigblue Happy Orders Scorecard — Metabase data fetcher ───────────────────
// Paste into Chrome DevTools console on any Metabase page.
// Downloads ho_data.json for use with generate_ho_html.py.

(async function () {
  const PIVOT_IDS   = [26830];                         // pivot-type visualisations
  const REGULAR_IDS = [26831, 26829, 26832];           // regular queries

  async function fetchOne(id, pivot) {
    const endpoint = pivot
      ? `/api/card/pivot/${id}/query`
      : `/api/card/${id}/query`;
    const r = await fetch(endpoint, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ignore_cache: true }),
    });
    const d = await r.json();
    return {
      id,
      cols: d.data.cols.map(c => c.name),
      rows: d.data.rows,
    };
  }

  console.log("⏳ Fetching Happy Orders data from Metabase (sequential)…");

  const results = [];
  for (const id of PIVOT_IDS) {
    console.log(`  → pivot query ${id}…`);
    results.push(await fetchOne(id, true));
  }
  for (const id of REGULAR_IDS) {
    console.log(`  → regular query ${id}…`);
    results.push(await fetchOne(id, false));
  }

  const blob = new Blob([JSON.stringify(results)], { type: "application/json" });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = "ho_data.json";
  a.click();
  URL.revokeObjectURL(url);
  console.log("✅ ho_data.json downloaded — now run ./update_ho.sh");
})();
