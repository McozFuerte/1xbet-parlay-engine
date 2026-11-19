---
name: 1xbet-quant-parlay-engine
description: Use when analyzing 1xBet parlay screenshots — run the bundled quantitative parlay engine (Shin's Method + Dixon-Coles 10x10 matrix, Monte Carlo, Asian O/U actuary, 3 slip recipes, hedging calculator). NEVER compute parlay probabilities by hand; always run scripts/parlay_engine.py.
---
# 1xBet Quantitative Parlay Engine v7.1

Operator-supplied engine (v7.1 FINAL AUDITED). Single source of truth for parlay math: Shin margin removal, Dixon-Coles scoreline matrix, exact Asian O/U actuary (half-win/half-loss/push), 10,000x Monte Carlo per match, trap detection, and 3 slip recipes (Tactical / Combo Booster / Jackpot Escalator) plus a 2-way hedging calculator.

## Workflow (from a screenshot)

1. Extract every match with full 1X2 odds (W1, X, W2) + kickoff `"DD.MM HH:MM"` or `"HH:MM"`. Skip aggregate specials ("Home vs Away 6 Matches"), finished games, and edge-cut odds rows.
2. Header competition: `"is_cup": true` for domestic cups (Copa, Cup, Pokal, Taca, FA Cup), `false` for leagues.
3. If O/U lines are visible (bet slip view), add optional `"avail_ou"` (e.g. `[1.25, 1.75]`) and `"real_o15_odds"` — the engine uses them to calibrate lambda and pick available lines only.
4. Run the engine — NEVER hand-calculate probabilities:

```bash
python3 <skill_dir>/scripts/parlay_engine.py '<matches_json>' --legs N --modal 10000
```

matches_json format:
```json
[{"name": "Team A vs Team B", "datetime": "19.11 06:30", "w1": 1.75, "x": 3.60, "w2": 4.50, "is_cup": false}]
```

`--legs` = however many legs the operator asked for (2, 3, 5, 7, 10 — flexible). `--modal` = stake in IDR (default 10000).

5. Show the engine's output VERBATIM AND IN FULL — the complete raw text (all analyzed matches, dropped list, Slip 1/2/3, hedging calculator) goes to the operator, not a rewritten summary. A compact Telegram table may be ADDED on top as a convenience, but never replaces the raw output.

6. Do NOT force every leg into W1/W2. The engine deliberately mixes markets (1X2, Asian O/U, Handicap, DC+Total) per risk profile — keep those picks exactly as the engine outputs them. O/U lines not visible in the screenshot is fine: the operator adapts the pick to the closest available line in the app himself. Do not pre-collapse picks to 1X2 just because the screenshot only showed 1X2 odds.

## Placement

Analysis only. Placement stays manual by operator (screenshot-based workflow); placement automation details live in `references/1xbet-placement-automation.md` and `references/1xbet-automation.md` if ever needed. BET GUARD: never place fewer legs than target.

## Layer 2 — Fundamental Cross-Check via Web Search

Runs AFTER Layer 1 (engine output). Mode is chosen from the operator's message:

- **Default** (no keyword): web search ONLY for teams in Slip 1 that are BANKER (pure 1X2) and the Anchor Leg (last leg).
- **Deep** (message contains "deep"): web search for ALL teams in Slip 1.
- **Fast** (message contains "fast"): skip web search entirely, deliver Layer 1 output as-is.

Mandatory checks per team searched:
1. Key injuries/suspensions — main striker, playmaker, or first-choice keeper recently out.
2. Motivation & rotation trap — team already qualified/top of group, or played 2-3 days ago (rotation risk).
3. Recent form — last-5 trend; watch favorites on losing streaks.

Output appended BELOW the engine output, exactly:

```
🔍 AUDIT FUNDAMENTAL (BERITA & FORM):
- [Team]: ✅ AMAN — (one-line reason: full squad, win streak, etc.)
- [Team]: 🚨 RED FLAG — (the danger) ➡️ Saran: turunkan ke Over/Under atau ganti dengan laga cadangan.
```

IMPORTANT: when the deliverable is presented as rich-message tables, the 🔍 AUDIT FUNDAMENTAL block MUST be included in the SAME message, directly below the last slip/hedging table — never delivered as a separate later message or reduced to a one-line mention.

Never skip the audit verdict line even in Default mode — un-searched teams are simply not listed. Sources used are stated briefly (model vs market divergence is worth flagging, e.g. a Squawka Signal or Kalshi probability that disagrees with the 1xBet line).

## Verifier & Placement References

- `scripts/simulate_parlay.py` (absorbed from parlay-probability-analyzer) — odds format converter + independent MC verifier: `python3 scripts/simulate_parlay.py --convert fractional 8/11`, `--convert american -275`, and `--combine selections.json` to double-check combined odds/hit probability on the engine's slip output.
- `references/1xbet-placement-automation.md` / `references/1xbet-automation.md` — browser automation details (canvas clicking, cf_clearance, SMS handshake) if operator ever asks for automated placement.

## Bet Guard

Always present combined odds together with combined win probability and the "meleset 1 tim" (N-1 of N) probability for Slip 1 & 3. Parlays are structurally -EV; the report must show that trade-off, not just the multiplier.
