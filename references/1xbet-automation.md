# 1xbet Live Automation Notes (Playwright on VPS)

Session-proven facts from live 1xbet automation (Nov 2026). Infrastructure: VPS + Playwright Chromium + local CF-clearance solver at `http://127.0.0.1:8877` (POST `{"type":"cloudflare","url":...}` → returns `cf_clearance` cookie to inject via `ctx.add_cookies([cf])` BEFORE any navigation).

## The critical discovery: market tables are rendered as CANVAS

1xbet's match-page market blocks (Total O/U, Handicap, BTTS, everything except the simple 1X2 row) are drawn into a `<canvas>` element (~1068×850px at x≈266) as an anti-scraper measure:

- `document.body.textContent` does NOT contain "Over 2.5", "W1", odds strings, etc. Only the inline Vue bootstrap script contains odds data (`cf:1.676` fragments inside `window.__V3_HOST_APP__`).
- `querySelector` for market text returns nothing. No shadow DOM, no iframes — the pixels ARE the interface.
- Screenshot + vision (OCR-by-LLM) is the ONLY reliable way to read markets. Reading works fine: take a clipped screenshot of the canvas, feed to vision, get odds + pixel coordinates.
- Clicking works fine too: `page.mouse.click(canvas.x + rel_x, canvas.y + rel_y)` at coordinates the vision call reports. One verified success: "Over 2.5" in the Total block at canvas-relative (144, 471), which registered in the bet slip ("Bet slip (1): Juventus – Unione Venezia, Total Over 2.5 @1.676").
- Coordinates shift per match/layout — always re-screenshot + re-vision per match; do not reuse coordinates blindly.
- Highlighted-yellow cells in vision output = hover/selected state, NOT confirmed slip addition. Always verify slip content by reading the bet slip panel text afterward.
- The simple 1X2 row on match pages may also be canvas; the line-page league lists (W1/X/W2 per row) render as normal DOM with `span.dashboard-markets__market` cells.

## Auth flow & session lifetimes

- Login: click header "LOG IN" → form → submit. SMS wall ("trying to log in from a new location") appears on new IP/device fingerprint; fill phone local part (e.g. `81274162463`), click SEND VIA SMS, wait for user to supply code in chat (write to `/tmp/apkrev/CODE.txt` file-signal pattern — browser stays alive, no resend), fill `input[placeholder*="code"]`, click CONFIRM.
- After a successful SMS confirm, subsequent logins from the same environment often skip SMS (device whitelisted) — but the wall recurs unpredictably. Always handle it.
- Cookie TTLs: `access_token` ≈ 1 hour; `refresh_token` ≈ 12h; `cf_clearance` ≈ 1 year. A betslip can silently log out mid-flow (header shows REGISTRATION/LOG IN, stake button becomes DEPOSIT). Check `document.cookie.includes('authenticated=')` before placing; check the slip for "REGISTRATION" button as the fail signal.

## Pipeline shape that works

1. Fresh `cf_clearance` from solver → inject pre-navigation.
2. Login (handle SMS wall).
3. Navigate league line page → collect `a[href*="/match/"]` links (real URLs; guessing league ID slugs 404s — use the sidebar or known IDs).
4. For each match: goto match page, scroll ~400px, screenshot canvas clipped, vision-extract odds AND click coordinates.
5. Click via mouse coordinates → verify slip count/odds text.
6. Odds verification gate: parse "overall odds" from slip text; abort if outside expected range (never place a mis-built slip).
7. Stake via native JS setter (`HTMLInputElement.prototype.value.set` + input/change events) on the stake input.
8. Place via `get_by_text(/place a bet|make a bet/i)`, wait ~10s, confirm from body text.

## Layout traps

- Global "Top Games" widget (e.g. Crystal Palace–Liverpool @5.54/4.625/1.616) appears on EVERY page and poisons naive first-match odds scrapes — scope extraction to the match-specific content or verify against the expected odds.
- Promo modal ("Place a bet on a top event") intercepts clicks — remove via `#modals-container .modal-content` cleanup, use `force=True` clicks.
- League page odds are lazy-rendered: wait ~20s + scroll before extraction. Match pages: block "Total" renders in-canvas regardless of scroll.
- Bet slip stake defaults (e.g. 50,000) exceed a 10,000 balance → Place button becomes DEPOSIT; always set the stake explicitly and confirm it reads back before placing.

## Solver ops

- The CF solver (captcha-solver at port 8877) runs headful (TURNSTILE_HEADLESS=0) and needs a live Xvfb. If it errors with "headed browser without XServer", restart it: `xvfb-run -a -s "-screen 0 1920x1080x24" ./.venv/bin/python3 server.py` from `~/scripts/captcha-solver/` (kill the stale one first — zombie xvfb-run parents block the port).
