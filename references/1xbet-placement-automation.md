# 1xbet Placement Automation (canvas market + Cloudflare + SMS handshake)

Session-verified workflow for building and placing a slip on 1xbet.com from a headless VPS
(Playwright + Chromium). Companion to the analysis flow in SKILL.md — this covers the
"operator asks the agent to place into their own account" case. Credentials must come from
the operator in-chat or session env; never hardcode them into skill files.

## Site rendering facts (durable until 1xbet changes its design)

- Market tables render inside **`<canvas>`** elements (≈1068×850). Odds do **not** exist as
  DOM text: `document.body.textContent` contains odds only inside inline `<script>` blobs
  (`cf:1.676`), never as queryable nodes. `elementFromPoint` on the market area returns the
  canvas, not per-odds elements.
- Consequence: selector-based scraping and clicking fail silently. The only working paths:
  (a) **screenshot → VLM coordinate mapping → `page.mouse.click(x,y)`**, or
  (b) replaying JSON feeds — which are Cloudflare-protected.
- The sidebar **"Top Games" widget renders real odds on every page** and pollutes any
  unscoped odds query (it will feed you Palace–Liverpool 5.54/4.625/1.616 as if they were
  the match you're scraping). Always scope queries or filter widget labels.

## Cloudflare

- `/service-api/*` feed endpoints return 403 "Just a moment…" from datacenter IPs even when
  the page shell loads fine.
- Local captcha-solver (`http://127.0.0.1:8877/solve`, body `{"type":"cloudflare","url":…}`)
  harvests a fresh `cf_clearance` cookie in ~15–20s. Inject via `ctx.add_cookies([cf])`
  **before** the first navigation.
- The solver is a headed browser: it fails with "headed browser without XServer" when Xvfb
  is down. Fix = kill the stale solver process, relaunch under `xvfb-run -a`, then
  `curl http://127.0.0.1:8877/health` to confirm. Do not treat a solver 500 as "CF is
  unsolvable" — check the display server first.
- Headless Chromium gets 403 where a headed browser passes. Prefer solver-issued clearance
  cookie + your own headless session over running the whole flow headful.

## Auth (access_token + SMS wall)

- `access_token` TTL ≈ 30–60 min. Plan the whole build-and-place inside one session or
  script the re-login.
- Login from a new fingerprint triggers an SMS wall ("trying to log in from a new
  location"). Verified handshake: fill local phone digits → **SEND VIA SMS** → browser
  holds the wall open while polling a code file (`CODE.txt`) → operator sends the code in
  chat → script writes it to the file → script fills code + CONFIRM. No resend, codes
  expire fast. Ask for the code as a direct chat question.
- Save `ctx.storage_state()` after **every** successful step; state dies with the process.
- Auth-expiry signal mid-flow: slip button becomes "REGISTRATION"/"DEPOSIT" and currency
  may flip IDR→SGD.

## Canvas coordinate clicking (verified end-to-end)

1. Navigate to the match page (find link on the league page via `a[href*="<slug>"]`).
2. `page.mouse.wheel(0, scroll)` to the market block, wait ≥2s.
3. Take a **full-page screenshot at this exact scroll offset** (not a canvas-clip — clip
   origins don't map to page coordinates, and the sticky header covers roughly the top 90px).
4. Vision model: "koordinat pixel pusat tombol <pick>" → returns x,y in image space, which
   equals page space for a full-viewport screenshot.
5. `page.mouse.move(x,y)` → wait ~500ms → `mouse.down()` → 100ms → `mouse.up()`.
6. **Verify by odds-progress**: read the slip's "Overall odds" before and after the click.
   It must *increase* when a leg is added. Unchanged = click missed; *decreased* = you
   toggled a leg off — re-click.
7. `storage_state()` save after each successful leg.

If a click "succeeds" but the slip doesn't change, run `document.elementFromPoint(x,y)` —
the usual culprit is the sticky navbar intercepting the point (see Pitfalls).

## Pitfalls

- Coordinates mapped from a **clip** screenshot fail on click — always map from full-page
  screenshots taken at the same scroll offset you'll click at.
- 1xbet removes started matches from the line mid-session (Marseille vs Le Mans vanished
  while a slip was being built). Re-verify each leg's match link exists before clicking;
  abort and report if a leg is gone rather than substituting a different match.
- The yellow highlight on odds cells is 1xbet's own decoration (line-change indicator),
  **not** your selection state. Selection state = the slip contents only.
- "Overall odds 7.941"-style popups ("Accumulator of the Day") are widgets unrelated to your
  slip — read odds from the slip panel, not from the first regex hit on the page.
- Escape-key modal dismissal + a fixed wait is enough for promo modals; use `force=True`
  clicks only on DOM elements, never on canvas coordinates.

## Operator preference (Piccolo — embed, do not improvise)

- Run placement scripts with `background=true` + `notify_on_complete` and **do not paste
  process logs into chat**. Report milestones only (leg added, odds verified, placed) and
  surface the SMS-code request as a direct question when the wall appears.
- Stay inside the requested scope (leagues/sport the operator named); don't widen domains
  or pivot to other projects mid-task.
- Parlays are structurally -EV: state EV and hit probability plainly with every slip
  (SKILL.md Gotchas already requires this — keep doing it in placement context too).

## Safety rails

- Verify the slip's "Overall odds" against the expected product of leg odds (±15% band)
  before clicking Place; abort on mismatch — odds move live.
- Expected payout = stake × combined odds; if the slip button shows DEPOSIT instead of
  Place, the stake exceeds balance — abort and report, never auto-deposit.
