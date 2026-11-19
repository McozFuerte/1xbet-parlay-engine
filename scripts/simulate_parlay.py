#!/usr/bin/env python3
"""
Parlay Probability Simulator — margin-adjusted true probabilities + 1000x Monte Carlo.

USAGE:
  1. Per-match analysis (1X2):
       python3 simulate_parlay.py matches.json
     matches.json format:
     [
       {"match": "Arsenal vs Chelsea", "w1": 1.85, "draw": 3.60, "w2": 4.20},
       ...
     ]

  2. Combine a selected slip (any markets, incl. O/U, DC, BTTS):
       python3 simulate_parlay.py --combine selections.json
     selections.json format:
     {
       "stake": 10000,
       "legs": [
         {"match": "Arsenal vs Chelsea", "market": "1X2", "pick": "W1", "odds": 1.85,
          "true_p": 0.541},
         {"match": "Marseille vs Le Mans", "market": "Total", "pick": "Over 2.5", "odds": 1.489,
          "pair_odds": {"other": 2.61}},
         {"match": "Nice vs PSG", "market": "1X2", "pick": "W2", "odds": 1.501}
       ]
     }
     Optional per-leg fields:
       "true_p"    — exact margin-normalized probability from a prior per-match run
                     (preferred when available; skips all estimation)
       "pair_odds" — the opposite side's odds so two-way margin can be normalized
                     instead of assuming a generic 6% overround
     For --combine, two-way markets (Total/BTTS) should include both sides so the
     margin can be normalized; pass "pair_odds": {"other": 2.566} on the leg
     (the opposite side's odds) — optional, falls back to 6% generic margin.

  3. Odds conversion:
       python3 simulate_parlay.py --convert fractional 8/11
       python3 simulate_parlay.py --convert american -275

OUTPUT:
  - Per-match: true probability (margin-normalized) + 1000-trial simulated frequencies.
  - --combine: combined decimal odds, combined true hit probability, EV on stake,
    trap ranking (which legs fail most often in simulation).
"""
import json
import random
import sys

N_SIM = 1000


def frac_to_dec(s: str) -> float:
    num, den = s.split("/")
    return float(num) / float(den) + 1.0


def am_to_dec(s: str) -> float:
    v = float(s)
    if v > 0:
        return 1.0 + v / 100.0
    return 1.0 + 100.0 / abs(v)


def true_probs_1x2(w1, dr, w2):
    raw = [1.0 / w1, 1.0 / dr, 1.0 / w2]
    over = sum(raw)
    return [r / over for r in raw], over  # (pW1, pX, pW2), overround


def true_probs_two(o_a, o_b=None):
    """Two-way market (Total O/U, BTTS). If other side unknown, assume 6% margin."""
    if o_b is None:
        o_b = 1.0 / ((1.0 / o_a) * 0.94)
    raw = [1.0 / o_a, 1.0 / o_b]
    over = sum(raw)
    return [raw[0] / over, raw[1] / over], over


def simulate(picks, n=N_SIM, seed=42):
    """picks: list of true probabilities (independent legs). Returns wins, fail counts."""
    rng = random.Random(seed)
    wins = 0
    fails = [0] * len(picks)
    for _ in range(n):
        ok = True
        for i, p in enumerate(picks):
            if rng.random() > p:
                fails[i] += 1
                ok = False
                break
        if ok:
            wins += 1
    return wins, fails


def cmd_matches(path):
    data = json.load(open(path))
    rows = []
    for m in data:
        (p1, px, p2), over = true_probs_1x2(m["w1"], m["draw"], m["w2"])
        rng = random.Random(hash(m["match"]) % 99999)
        sims = [0, 0, 0]
        for _ in range(N_SIM):
            r = rng.random()
            if r < p1:
                sims[0] += 1
            elif r < p1 + px:
                sims[1] += 1
            else:
                sims[2] += 1
        dc1x = p1 + px
        dc12 = p1 + p2
        dc2x = px + p2
        dnb1 = p1 / (p1 + p2)
        dnb2 = p2 / (p1 + p2)
        rows.append({
            "match": m["match"],
            "odds": {"w1": m["w1"], "draw": m["draw"], "w2": m["w2"]},
            "overround": round(over, 4),
            "true_probability": {"w1": round(p1, 4), "draw": round(px, 4), "w2": round(p2, 4)},
            "simulated": {"w1": sims[0] / N_SIM, "draw": sims[1] / N_SIM, "w2": sims[2] / N_SIM},
            "double_chance": {"1X": round(dc1x, 4), "12": round(dc12, 4), "2X": round(dc2x, 4)},
            "draw_no_bet": {"w1": round(dnb1, 4), "w2": round(dnb2, 4)},
            "trap_flag": (max(p1, p2) < 0.50 and min(m["w1"], m["w2"]) <= 1.95),
        })
    print(json.dumps(rows, indent=1))
    print("\nTRAPS (fav true<50% but odds<=1.95):",
          [r["match"] for r in rows if r["trap_flag"]] or "none")


def cmd_combine(path):
    slip = json.load(open(path))
    legs = slip["legs"]
    stake = slip.get("stake", 10000)
    picks = []
    total_odds = 1.0
    for l in legs:
        o = l["odds"]
        total_odds *= o
        po = l.get("pair_odds")
        if isinstance(po, dict):
            po = po.get("other")
        if l.get("true_p"):
            # explicit true probability supplied (from a prior per-match run)
            picks.append(float(l["true_p"]))
        elif po:
            (pa, _), _ = true_probs_two(o, po)
            picks.append(pa)
        elif l.get("market") == "1X2":
            # 3-way market without pair data: assume 6% overround, p = raw/overround
            picks.append((1.0 / o) / 1.06)
        else:
            (pa, _), _ = true_probs_two(o)
            picks.append(pa)
    p_hit = 1.0
    for p in picks:
        p_hit *= p
    wins, fails = simulate(picks, seed=7)
    ev = p_hit * total_odds * stake - stake
    out = {
        "legs": legs,
        "combined_odds": round(total_odds, 3),
        "combined_hit_probability": round(p_hit, 4),
        "mc_hit_rate": wins / N_SIM,
        "stake": stake,
        "payout": round(stake * total_odds, 0),
        "ev": round(ev, 0),
        "trap_ranking": sorted(
            [{"match": legs[i]["match"], "pick": legs[i]["pick"],
              "fail_pct": round(fails[i] / N_SIM * 100, 1)} for i in range(len(legs))],
            key=lambda x: -x["fail_pct"]),
    }
    print(json.dumps(out, indent=1, ensure_ascii=False))


def main():
    args = sys.argv[1:]
    if "--convert" in args:
        i = args.index("--convert")
        kind, val = args[i + 1], args[i + 2]
        dec = frac_to_dec(val) if kind.startswith("frac") else am_to_dec(val)
        print(json.dumps({"input": f"{kind} {val}", "decimal": round(dec, 4),
                          "implied_raw": round(1 / dec, 4)}))
        return
    if "--combine" in args:
        i = args.index("--combine")
        cmd_combine(args[i + 1])
        return
    if not args:
        print(__doc__)
        return
    cmd_matches(args[0])


if __name__ == "__main__":
    main()
