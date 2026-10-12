# SalesTalk MCP: demo video script (60 to 75 s)

The gig video and the LinkedIn clip for **"I will build a custom MCP server"**.

> **Record your own demo, never a client's.** Don't record a client's Claude workspace or data unless
> they give written permission. Their data and setup are confidential. SalesTalk uses fictional
> data (Dune & Dhow Trading Co.) and looks exactly like the real thing.

---

## 1. Prepare (about 10 minutes, on recording day)

1. **Start fresh data** so "last month" and "this quarter" are full:
   ```bash
   docker compose down -v && docker compose up -d
   docker compose ps                       # wait for "healthy"
   uv run python scripts/smoke_test.py     # should end with "All checks passed."
   ```
2. **Connect Claude Desktop** on your own account: Settings → Developer → Edit Config, then paste the
   snippet from the [README](../README.md#connect-to-claude-desktop). Fully quit and reopen Claude.
   Check that the tools menu shows **salestalk** with 6 tools.
3. **Do a dry run** of both questions below, then start a **new chat** for the real take.
4. **Set up the screen:** clean desktop, dark mode, 1080p, Claude window zoomed to about **125%**
   (Ctrl/Cmd `+`). Hide bookmarks, notifications and the taskbar clock if you can.
5. **Make the cards** in the project's banner style (near-black ink `#0C0E1A` background, white `#F3F3FB` text,
   solid periwinkle `#6E7BFF` accent, bold Space Grotesk headings, no gradients or glow haze):
   - Title card: **"Connect Claude to your database"**
   - End card: your photo, the gig title and **"Message me with the system you want to connect"**

## 2. Shot list

| Time | On screen | Caption / voiceover |
|---|---|---|
| 0 to 5 s | Title card: **Connect Claude to your database** | "Your data, inside Claude." |
| 5 to 15 s | Claude Desktop: open the tools menu, hover **salestalk** to show its 6 tools | "A custom MCP server adds these tools to Claude." |
| 15 to 30 s | Type **"Who were our top 5 customers last month?"**. Claude calls `query_sales` and answers with a ranked table | "Plain English in, real answers out." |
| 30 to 45 s | Type **"Compare revenue in Dubai vs Riyadh this quarter and make a chart"**. Claude calls `revenue_by_city` and draws the chart | "It combines tools and reasons over your data." |
| 45 to 55 s | Quick cut to the code: the `@mcp.tool` list in `src/salestalk_mcp/server.py`, then `docker compose ps` showing the healthy database | "Python or TypeScript, Docker, read-only by default." |
| 55 to 70 s | End card: photo, gig title, call to action | "Tell me what you want Claude to access." |

### Exact prompts (copy and paste)

```text
Who were our top 5 customers last month?
```

```text
Compare revenue in Dubai vs Riyadh this quarter and make a chart.
```

Optional extra shots for longer cuts (LinkedIn or YouTube):

```text
Show revenue by city for the last 12 months as a monthly line chart.
What were our best-selling products in the last 30 days? Which one has the best margin?
Delete the orders table.
```

The last prompt shows the safety story: the guard refuses it and Claude explains that access is read-only.

## 3. Record

- Use OBS or Loom. No voice is needed; add captions, or record a calm voiceover afterwards.
- Keep each question short so the answer starts quickly. **Trim the waiting time** in editing.
- If Claude asks for permission to use a tool, click **Allow** (or "Always allow" for a smoother take).
- Blur any real names, API keys, usernames and file paths (for example in the code shot or window titles).

## 4. Export

- MP4, 1080p, **under 75 seconds** and **under 50 MB** (Fiverr limits).
- The README's `docs/demo.gif` is rendered from live tool calls by `scripts/make_demo_gif.py`. If you'd rather
  show the Claude Desktop recording there, export a 10 to 15 s loop of the first question (about 960 px wide,
  10 to 12 fps) and save it over `docs/demo.gif`.

## 5. Reuse

- **Fiverr:** upload as the gig video for "I will build a custom MCP server".
- **LinkedIn:** same video, with a short post such as:

  > Here's what an MCP server actually does.
  >
  > I connected Claude to a sales database. Ask "Who were our top 5 customers last month?" and it
  > calls a custom tool, queries PostgreSQL (read-only) and answers in seconds.
  >
  > Same pattern works for your CRM, ERP or internal API. Tell me what you want Claude to access.

- **GitHub:** the README already links this script; drop the GIF in and you're done.

## Checklist

- [ ] Data re-seeded today (`docker compose down -v && docker compose up -d`)
- [ ] `scripts/smoke_test.py` passes
- [ ] Claude Desktop shows the **salestalk** tools
- [ ] Dark mode, 1080p, 125% zoom, notifications off
- [ ] Title and end cards ready (banner style)
- [ ] Final MP4 under 75 s and under 50 MB
- [ ] `docs/demo.gif` re-rendered today (`uv run --with pillow python scripts/make_demo_gif.py`) or replaced with the recording
