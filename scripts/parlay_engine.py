#!/usr/bin/env python3
"""
HERMES AI AGENT - 1xBET QUANTITATIVE PARLAY ENGINE v7.1 (FINAL AUDITED)
-----------------------------------------------------------------------
Perbaikan Final v7.1:
1. [FIX u225] Rumus Total Under (2.25) diperbaiki menjadi p_half_win=p_2 (2 Gol = Half-Win).
2. [FIX YEAR] Menghapus hardcode tahun 2026 pada build_unified_sort_keys menjadi dinamis (datetime.now()).
"""

import sys
import re
import json
import math
import argparse
from datetime import datetime, timedelta
import numpy as np

# =====================================================================
# 1. SYSTEM PROMPT & TOOL SCHEMA UNTUK HERMES AGENT (9ROUTER)
# =====================================================================
AGENT_SYSTEM_PROMPT = """
[1xBET QUANTITATIVE PARLAY SKILL v7.1 - FINAL EDITION]
Setiap kali pengguna mengirim screenshot jadwal/odds dari aplikasi 1xBet:
1. Ekstrak semua pertandingan yang memiliki odds 1X2 (W1, X, W2) secara utuh.
2. Ekstrak tanggal & jam kick-off dengan format "DD.MM HH:MM" atau "HH:MM" (contoh: "19.11 06:30").
3. ABAIKAN pasar spesial/agregat (seperti "Home vs Away 6 Matches"), laga yang sudah selesai, atau pertandingan di tepi layar yang angka odds-nya terpotong.
4. Cek header kompetisi: set `"is_cup": true` jika piala domestik (Copa, Cup, Pokal, Taca, FA Cup), dan `"is_cup": false` jika liga reguler.
5. Jika di screenshot terlihat garis Over/Under spesifik yang tersedia (misal di Bet Slip), masukkan ke field opsional `"avail_ou"` (contoh: `[1.25, 1.75]`) dan `"real_o15_odds"`.
6. Sesuaikan parameter `target_legs` dengan jumlah tim yang diminta user di chat (fleksibel: bisa 2, 3, 5, 7, 10 tim, dst).
7. DILARANG menghitung probabilitas sendiri. Wajib panggil tool `run_1xbet_parlay_engine` dan tampilkan outputnya secara utuh.
"""

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "run_1xbet_parlay_engine",
        "description": "Menjalankan 10.000x simulasi Monte Carlo (Shin's Method + 10x10 Dixon-Coles Matrix) dengan aktuaria Asian O/U eksak, meracik 3 Slip Parlay 1xBet fleksibel, dan kalkulator Hedging 2-arah.",
        "parameters": {
            "type": "object",
            "properties": {
                "matches_json": {
                    "type": "string",
                    "description": "JSON string array pertandingan. Contoh: '[{\"name\": \"Tim A vs Tim B\", \"datetime\": \"19.11 06:30\", \"w1\": 1.75, \"x\": 3.60, \"w2\": 4.50, \"is_cup\": false}]'"
                },
                "target_legs": {
                    "type": "integer",
                    "description": "Jumlah tim fleksibel dalam parlay sesuai permintaan user (default: 7)."
                },
                "modal": {
                    "type": "integer",
                    "description": "Total modal taruhan dalam Rupiah (default: 10000)."
                }
            },
            "required": ["matches_json"]
        }
    }
}


# =====================================================================
# 2. SANITIZER, FUZZY DEDUPLICATOR & MIDNIGHT-SAFE TIMELINE
# =====================================================================
def safe_float(val, default=None):
    """Mengonversi string angka (termasuk format koma '2,591') menjadi float secara aman."""
    if val is None:
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", ".")
    s = re.sub(r"[^0-9.]", "", s)
    try:
        return float(s)
    except ValueError:
        return default


def extract_valid_json(raw_input):
    """Mengekstrak struktur JSON secara aman meskipun dibungkus markdown atau teks percakapan LLM."""
    if isinstance(raw_input, (list, dict)):
        return raw_input
    text = str(raw_input).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    code_block = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if code_block:
        try:
            return json.loads(code_block.group(1).strip())
        except Exception:
            pass
    start_arr, end_arr = text.find("["), text.rfind("]")
    start_obj, end_obj = text.find("{"), text.rfind("}")
    if start_arr != -1 and end_arr > start_arr and (start_obj == -1 or start_arr < start_obj):
        try:
            return json.loads(text[start_arr:end_arr + 1])
        except Exception:
            pass
    if start_obj != -1 and end_obj > start_obj:
        try:
            return json.loads(text[start_obj:end_obj + 1])
        except Exception:
            pass
    raise ValueError("Tidak ditemukan struktur JSON yang valid pada input.")


def extract_team_tokens(name: str):
    """Memecah nama pertandingan menjadi token kata penting (mengabaikan kata umum seperti fc, clube, de)."""
    stop_words = {
        "vs", "v", "fc", "cf", "cd", "ec", "sc", "ac", "clube", "club", "de",
        "do", "da", "esporte", "atletico", "sociedade", "esportiva", "futebol",
        "regatas", "paulista", "alegrense", "porto"
    }
    tokens = re.findall(r"[a-z0-9]+", str(name).lower())
    filtered = [t for t in tokens if t not in stop_words and len(t) > 2]
    return set(filtered) if filtered else set(tokens)


def deduplicate_and_merge_matches(raw_matches):
    """
    Menghapus pertandingan duplikat antar-screenshot menggunakan Token Jaccard Similarity
    dan menggabungkan informasi tambahan (seperti real_o15_odds atau avail_ou) jika ada.
    """
    unique = []
    token_sets = []

    for m in raw_matches:
        if not isinstance(m, dict) or "name" not in m:
            continue
        w1 = safe_float(m.get("w1"))
        x  = safe_float(m.get("x"))
        w2 = safe_float(m.get("w2"))
        if not (w1 and x and w2):
            continue

        t_set = extract_team_tokens(m["name"])
        is_dup = False
        for idx, existing_set in enumerate(token_sets):
            if not t_set or not existing_set:
                continue
            intersection = len(t_set & existing_set)
            min_len = min(len(t_set), len(existing_set))
            if (min_len >= 2 and intersection >= 2) or (intersection / max(1, min_len) >= 0.65):
                is_dup = True
                if m.get("real_o15_odds") and not unique[idx].get("real_o15_odds"):
                    unique[idx]["real_o15_odds"] = m["real_o15_odds"]
                if m.get("avail_ou") and not unique[idx].get("avail_ou"):
                    unique[idx]["avail_ou"] = m["avail_ou"]
                if len(str(m.get("datetime", ""))) > len(str(unique[idx].get("datetime", ""))):
                    unique[idx]["datetime"] = m["datetime"]
                break

        if not is_dup:
            clean_m = dict(m)
            clean_m["w1"], clean_m["x"], clean_m["w2"] = w1, x, w2
            unique.append(clean_m)
            token_sets.append(t_set)

    return unique


def build_unified_sort_keys(matches_list):
    """
    Menyamakan timeline tanggal referensi secara dinamis & menangani pergantian hari (Midnight Rollover)
    agar laga jam 23:00 malam dan 02:30 dini hari tidak pernah terbalik urutannya.
    """
    now = datetime.now()
    ref_date = datetime(now.year, now.month, now.day)
    has_evening_hours = False

    for m in matches_list:
        dt_raw = re.sub(r"\s+", " ", str(m.get("datetime", m.get("time", ""))).strip())
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m %H:%M", "%Y-%m-%d %H:%M", "%H:%M"):
            try:
                parsed = datetime.strptime(dt_raw, fmt)
                if parsed.hour >= 18:
                    has_evening_hours = True
                if fmt != "%H:%M":
                    if fmt == "%d.%m %H:%M":
                        parsed = parsed.replace(year=now.year)
                    ref_date = datetime(parsed.year, parsed.month, parsed.day)
                break
            except ValueError:
                continue

    sort_keys = []
    for m in matches_list:
        dt_raw = re.sub(r"\s+", " ", str(m.get("datetime", m.get("time", "99:99"))).strip())
        key_val = 999999999
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m %H:%M", "%Y-%m-%d %H:%M", "%H:%M"):
            try:
                parsed = datetime.strptime(dt_raw, fmt)
                if fmt == "%H:%M":
                    dt_full = ref_date.replace(hour=parsed.hour, minute=parsed.minute)
                    if has_evening_hours and parsed.hour < 11:
                        dt_full += timedelta(days=1)
                    key_val = int(dt_full.timestamp() // 60)
                else:
                    if fmt == "%d.%m %H:%M":
                        parsed = parsed.replace(year=ref_date.year)
                    key_val = int(parsed.timestamp() // 60)
                break
            except ValueError:
                continue
        sort_keys.append(key_val)
    return sort_keys


def shins_true_probability(w1: float, x: float, w2: float):
    """Pembersih margin 1xBet menggunakan Power/Shin Method (koreksi bias tim tamu/seri)."""
    w1, x, w2 = max(1.01, float(w1)), max(1.01, float(x)), max(1.01, float(w2))
    q1, qx, q2 = 1.0 / w1, 1.0 / x, 1.0 / w2
    overround = q1 + qx + q2
    margin = max(0.0, (overround - 1.0) * 100.0)

    k = 1.0
    for _ in range(25):
        f = (q1 ** k) + (qx ** k) + (q2 ** k) - 1.0
        df = (q1 ** k) * math.log(q1) + (qx ** k) * math.log(qx) + (q2 ** k) * math.log(q2)
        if abs(df) < 1e-9:
            break
        k -= (f / df)
        k = max(0.1, min(5.0, k))

    p1, px, p2 = (q1 ** k), (qx ** k), (q2 ** k)
    tot = p1 + px + p2
    return p1 / tot, px / tot, p2 / tot, margin


# =====================================================================
# 3. 10x10 DIXON-COLES MATRIX & CONDITIONAL NON-PUSH VIG ACTUARY
# =====================================================================
def actuarial_asian_odds(p_full_win: float, p_half_win: float = 0.0, p_push: float = 0.0,
                         p_half_loss: float = 0.0, vig_factor: float = 0.935) -> float:
    """
    Rumus Aktuaria Sportsbook Eksak (Conditional Non-Push Vig Formula):
    Margin bandar (1 - vig_factor) hanya dikenakan pada porsi taruhan yang tidak berakhir Push/Void (1 - p_push).
    """
    non_push_mass = max(0.02, 1.0 - p_push)
    target_return = vig_factor * non_push_mass
    denom = max(0.005, p_full_win + 0.5 * p_half_win)
    numer = max(0.005, target_return - (0.5 * p_half_win + 0.5 * p_half_loss))
    raw_odds = numer / denom
    return round(max(1.06, raw_odds), 3)


def build_1xbet_markets(p1: float, px: float, p2: float, fav_pick: str, fav_odds: float,
                        is_cup: bool = False, real_o15=None, avail_ou=None):
    """Membangun matriks skor 10x10 Dixon-Coles & menghitung seluruh harga pasar 1xBet secara akurat."""
    imbalance = abs(p1 - p2)
    base_lambda = 2.68 - (px - 0.26) * 5.8 + (imbalance * 0.48)
    if is_cup:
        base_lambda *= 0.84
    total_lambda = max(1.55, min(3.65, base_lambda))

    ro15 = safe_float(real_o15)
    if ro15 and 1.05 < ro15 < 2.50:
        imp_o15 = min(0.93, 0.935 / ro15)
        lam_est = total_lambda
        for _ in range(12):
            p_u15 = math.exp(-lam_est) * (1.0 + lam_est)
            err = (1.0 - p_u15) - imp_o15
            d_err = lam_est * math.exp(-lam_est)
            if d_err > 1e-6:
                lam_est -= err / d_err
        total_lambda = max(1.50, min(3.85, lam_est))

    share_h = p1 + 0.5 * px
    lam_h = max(0.38, total_lambda * share_h)
    lam_a = max(0.32, total_lambda * (1.0 - share_h))
    rho = -0.13 if (is_cup or px >= 0.285) else -0.06

    matrix = np.zeros((10, 10))
    for h in range(10):
        for a in range(10):
            base_p = (math.exp(-lam_h) * (lam_h ** h) / math.factorial(h)) * \
                     (math.exp(-lam_a) * (lam_a ** a) / math.factorial(a))
            tau = 1.0
            if h == 0 and a == 0:
                tau = 1.0 - (lam_h * lam_a * rho)
            elif h == 0 and a == 1:
                tau = 1.0 + (lam_h * rho)
            elif h == 1 and a == 0:
                tau = 1.0 + (lam_a * rho)
            elif h == 1 and a == 1:
                tau = 1.0 - rho
            matrix[h, a] = max(0.0, base_p * tau)

    matrix /= np.sum(matrix)

    p_goals = [0.0] * 19
    p_fav_o15 = 0.0
    p_fav_dc_o15, p_fav_dc_u35 = 0.0, 0.0
    p_fav_margin_1 = 0.0
    p_fav_margin_2p = 0.0

    for h in range(10):
        for a in range(10):
            prob = matrix[h, a]
            tot = h + a
            p_goals[tot] += prob

            diff = (h - a) if fav_pick == "W1" else (a - h)
            if diff == 1:
                p_fav_margin_1 += prob
            elif diff >= 2:
                p_fav_margin_2p += prob

            if diff > 0 and tot >= 2:
                p_fav_o15 += prob
            if diff >= 0 and tot >= 2:
                p_fav_dc_o15 += prob
            if diff >= 0 and tot <= 3:
                p_fav_dc_u35 += prob

    p_0 = p_goals[0]
    p_1 = p_goals[1]
    p_2 = p_goals[2]
    p_0_1 = p_0 + p_1
    p_2p = sum(p_goals[2:])
    p_3p = sum(p_goals[3:])

    bf = 0.935
    dc_label = "1X" if fav_pick == "W1" else "2X"

    # Katalog Lengkap & Terverifikasi Semua Garis Over/Under 1xBet
    ou_catalog = {
        "o125": {
            "line": 1.25, "type": "over", "is_exact_2way": False,
            "name": "Total Over (1.25) [1 Gol=Half-Loss]",
            "odds": actuarial_asian_odds(p_full_win=p_2p, p_half_loss=p_1, vig_factor=bf),
            "win_prob": p_2p,
            "safe": 1.0 - p_0
        },
        "o150": {
            "line": 1.5, "type": "over", "is_exact_2way": True,
            "name": "Total Over (1.5)",
            "odds": actuarial_asian_odds(p_full_win=p_2p, vig_factor=bf),
            "win_prob": p_2p,
            "safe": p_2p
        },
        "o175": {
            "line": 1.75, "type": "over", "is_exact_2way": False,
            "name": "Total Over (1.75) [2 Gol=Half-Win]",
            "odds": actuarial_asian_odds(p_full_win=p_3p, p_half_win=p_2, vig_factor=bf),
            "win_prob": p_3p,
            "safe": p_2p
        },
        "o200": {
            "line": 2.0, "type": "over", "is_exact_2way": False,
            "name": "Total Over (2.0) [2 Gol=Void/Refund]",
            "odds": actuarial_asian_odds(p_full_win=p_3p, p_push=p_2, vig_factor=bf),
            "win_prob": p_3p,
            "safe": p_2p
        },
        "o225": {
            "line": 2.25, "type": "over", "is_exact_2way": False,
            "name": "Total Over (2.25) [2 Gol=Half-Loss]",
            "odds": actuarial_asian_odds(p_full_win=p_3p, p_half_loss=p_2, vig_factor=bf),
            "win_prob": p_3p,
            "safe": p_2p
        },
        "u250": {
            "line": 2.5, "type": "under", "is_exact_2way": True,
            "name": "Total Under (2.5)",
            "odds": actuarial_asian_odds(p_full_win=p_0_1 + p_2, vig_factor=bf),
            "win_prob": p_0_1 + p_2,
            "safe": p_0_1 + p_2
        },
        "u225": {
            "line": 2.25, "type": "under", "is_exact_2way": False,
            "name": "Total Under (2.25) [2 Gol=Half-Win]",
            "odds": actuarial_asian_odds(p_full_win=p_0_1, p_half_win=p_2, vig_factor=bf),
            "win_prob": p_0_1,
            "safe": p_0_1 + p_2
        },
        "u175": {
            "line": 1.75, "type": "under", "is_exact_2way": False,
            "name": "Total Under (1.75) [2 Gol=Half-Loss]",
            "odds": actuarial_asian_odds(p_full_win=p_0_1, p_half_loss=p_2, vig_factor=bf),
            "win_prob": p_0_1,
            "safe": p_0_1 + p_2
        },
        "u150": {
            "line": 1.5, "type": "under", "is_exact_2way": True,
            "name": "Total Under (1.5)",
            "odds": actuarial_asian_odds(p_full_win=p_0_1, vig_factor=bf),
            "win_prob": p_0_1,
            "safe": p_0_1
        }
    }

    avail_set = set()
    if isinstance(avail_ou, list):
        for val in avail_ou:
            f_val = safe_float(val)
            if f_val:
                avail_set.add(f_val)

    def select_best_over(require_exact_2way=False):
        if require_exact_2way:
            return ou_catalog["o150"]
        candidates = ["o150", "o175", "o200", "o125", "o225"]
        if avail_set:
            filtered = [k for k in candidates if ou_catalog[k]["line"] in avail_set]
            if filtered:
                candidates = filtered
        for k in candidates:
            if ou_catalog[k]["odds"] >= 1.24:
                return ou_catalog[k]
        return ou_catalog[candidates[0]]

    def select_best_under(require_exact_2way=False):
        if require_exact_2way:
            return ou_catalog["u250"]
        candidates = ["u225", "u250", "u175", "u150"]
        if avail_set:
            filtered = [k for k in candidates if ou_catalog[k]["line"] in avail_set]
            if filtered:
                candidates = filtered
        return ou_catalog[candidates[0]]

    alt_over_str = (
        f"O1.25 `@{ou_catalog['o125']['odds']:.2f}` | "
        f"O1.5 `@{ou_catalog['o150']['odds']:.2f}` | "
        f"O1.75 `@{ou_catalog['o175']['odds']:.2f}` | "
        f"O2.0 `@{ou_catalog['o200']['odds']:.2f}`"
    )
    alt_under_str = (
        f"U2.5 `@{ou_catalog['u250']['odds']:.2f}` | "
        f"U2.25 `@{ou_catalog['u225']['odds']:.2f}` | "
        f"U1.5 `@{ou_catalog['u150']['odds']:.2f}`"
    )

    odds_hdp_10 = max(
        round(fav_odds * 1.18, 3),
        actuarial_asian_odds(p_full_win=p_fav_margin_2p, p_push=p_fav_margin_1, vig_factor=bf)
    )
    odds_hdp_15 = max(
        round(fav_odds * 1.32, 3),
        actuarial_asian_odds(p_full_win=p_fav_margin_2p, vig_factor=bf)
    )
    odds_fav_o15 = max(
        round(fav_odds * 1.15, 3),
        actuarial_asian_odds(p_full_win=p_fav_o15, vig_factor=bf)
    )

    return {
        "lambda": round(total_lambda, 2),
        "best_over": select_best_over(False),
        "best_under": select_best_under(False),
        "exact_over_15": select_best_over(True),
        "exact_under_25": select_best_under(True),
        "alt_over_str": alt_over_str,
        "alt_under_str": alt_under_str,
        "ou_catalog": ou_catalog,
        "dc_o15": {
            "name": f"{dc_label} & Total Over (1.5)",
            "odds": actuarial_asian_odds(p_full_win=p_fav_dc_o15, vig_factor=bf),
            "safe": p_fav_dc_o15
        },
        "dc_u35": {
            "name": f"{dc_label} & Total Under (3.5)",
            "odds": actuarial_asian_odds(p_full_win=p_fav_dc_u35, vig_factor=bf),
            "safe": p_fav_dc_u35
        },
        "hdp_10": {
            "name": f"{fav_pick} Handicap (-1.0) [1 Gol=Void]",
            "odds": odds_hdp_10,
            "win": p_fav_margin_2p,
            "safe": p_fav_margin_2p + p_fav_margin_1
        },
        "hdp_15": {
            "name": f"{fav_pick} Handicap (-1.5)",
            "odds": odds_hdp_15,
            "win": p_fav_margin_2p
        },
        "win_o15": {
            "name": f"{fav_pick} & Total Over (1.5)",
            "odds": odds_fav_o15,
            "win": p_fav_o15
        }
    }


def calc_heartbreak_prob(probs):
    """Menghitung peluang terjadinya tragedi 'Meleset 1 Tim' (Tembus N-1 dari N tim)."""
    n = len(probs)
    if n < 2:
        return 0.0
    total_miss_1 = 0.0
    for i in range(n):
        p_fail_i = 1.0 - probs[i]
        p_others_win = 1.0
        for j in range(n):
            if i != j:
                p_others_win *= probs[j]
        total_miss_1 += (p_fail_i * p_others_win)
    return total_miss_1


# =====================================================================
# 4. MAIN PARLAY ENGINE v7.1
# =====================================================================
def run_1xbet_parlay_engine(matches_json, target_legs: int = 7, modal: int = 10000) -> str:
    try:
        data = extract_valid_json(matches_json)
        raw_matches = data.get("matches", data) if isinstance(data, dict) else data
    except Exception as e:
        return f"❌ Gagal memproses format JSON pertandingan: {str(e)}"

    if not raw_matches or not isinstance(raw_matches, list):
        return "❌ Data pertandingan kosong atau format JSON tidak valid."

    modal_val = safe_float(modal, 10000.0)
    modal_int = max(1000, int(modal_val))

    matches = deduplicate_and_merge_matches(raw_matches)
    if not matches:
        return "❌ Tidak ada pertandingan dengan format odds 1X2 yang valid."

    sort_keys = build_unified_sort_keys(matches)

    iterations = 10000
    np.random.seed(42)
    analyzed = []

    for idx, m in enumerate(matches):
        name = str(m["name"]).strip()
        dt_str = str(m.get("datetime", m.get("time", "99:99"))).strip()
        w1, x, w2 = m["w1"], m["x"], m["w2"]
        is_cup = bool(m.get("is_cup", False))
        real_o15 = m.get("real_o15_odds", None)
        avail_ou = m.get("avail_ou", None)

        p1, px, p2, margin = shins_true_probability(w1, x, w2)

        outcomes = np.random.choice(["W1", "X", "W2"], size=iterations, p=[p1, px, p2])
        sim_1000 = {
            "W1": round(np.sum(outcomes == "W1") / 10),
            "X":  round(np.sum(outcomes == "X")  / 10),
            "W2": round(np.sum(outcomes == "W2") / 10)
        }

        entropy = -(p1 * math.log2(p1) + px * math.log2(px) + p2 * math.log2(p2))
        max_p = max(p1, p2)
        fav_pick = "W1" if p1 >= p2 else "W2"
        fav_odds = w1 if p1 >= p2 else w2
        is_trap = (max_p < 0.435) or (entropy > 1.545)

        mkts = build_1xbet_markets(
            p1, px, p2, fav_pick, fav_odds,
            is_cup=is_cup, real_o15=real_o15, avail_ou=avail_ou
        )

        analyzed.append({
            "name": name, "datetime": dt_str, "sort_key": sort_keys[idx],
            "w1": w1, "x": x, "w2": w2, "is_cup": is_cup,
            "p1": p1, "px": px, "p2": p2, "margin": margin,
            "fav_pick": fav_pick, "fav_odds": fav_odds, "max_p": max_p,
            "entropy": round(entropy, 3), "is_trap": is_trap, "sim_1000": sim_1000,
            "mkts": mkts
        })

    total_available = len(analyzed)
    req_legs = int(safe_float(target_legs, 7))
    actual_legs = max(1, min(req_legs, total_available))

    sorted_m = sorted(analyzed, key=lambda k: (k["max_p"], -k["margin"]), reverse=True)
    selected = sorted_m[:actual_legs]
    dropped  = sorted_m[actual_legs:]
    selected_chrono = sorted(selected, key=lambda k: k["sort_key"])

    # =================================================================
    # OUTPUT LAPORAN LENGKAP
    # =================================================================
    out = [f"📊 *AUDIT KUANTITATIF 1xBET v7.1 FINAL ({actual_legs} TIM DARI {total_available} LAGA)*"]
    for a in analyzed:
        st = "⚠️ *JEBAKAN*" if a["is_trap"] else ("🔒 *BANKER*" if a["max_p"] >= 0.60 else "✅ *VALUE*")
        t_str = f"`[{a['datetime']}]` " if a["datetime"] != "99:99" else ""
        out.append(
            f"• {t_str}*{a['name']}* ({st} | Est. xG: `{a['mkts']['lambda']}`)\n"
            f"  Murni (Shin): `{a['p1']*100:.1f}% | {a['px']*100:.1f}% | {a['p2']*100:.1f}%` (Vig: `{a['margin']:.1f}%`)\n"
            f"  Simulasi 1000x: `W1: {a['sim_1000']['W1']} | X: {a['sim_1000']['X']} | W2: {a['sim_1000']['W2']}`"
        )

    if dropped:
        out.append(f"\n❌ *{len(dropped)} LAGA JEBAKAN YANG WAJIB DIBUANG (SKIP):*")
        for d in dropped:
            out.append(f"• ~{d['name']}~ (Favorit cuma `{d['max_p']*100:.1f}%` | Entropi `{d['entropy']}` ➡️ Pemutus Parlay)")

    # -----------------------------------------------------------------
    # SLIP 1: TACTICAL MEDIUM RISK (Dengan Optimal 2-Way Anchor Lock)
    # -----------------------------------------------------------------
    out.append(f"\n🎯 *SLIP 1: TACTICAL MEDIUM RISK ({actual_legs} TIM — URUT JAM KICK-OFF)*")
    m_odds, m_probs = 1.0, []
    last_leg_info = {}
    for i, m in enumerate(selected_chrono, 1):
        t_str = f"`[{m['datetime']}]` " if m["datetime"] != "99:99" else ""
        is_last_leg = (i == len(selected_chrono))

        if is_last_leg:
            opt_2way_ou = m["mkts"]["exact_under_25"] if (m["is_cup"] or m["px"] >= 0.285) else m["mkts"]["exact_over_15"]
            if not m["is_trap"] and m["max_p"] >= opt_2way_ou["safe"]:
                pick, odds, prob = f"*{m['fav_pick']}* (1X2 Mutlak)", m["fav_odds"], m["max_p"]
                hedge_label = "X2 (Lawan Menang/Seri)" if m["fav_pick"] == "W1" else "1X (Tuan Rumah Menang/Seri)"
                alt_line_note = f"   ↳ _Anchor 2-Arah Murni (Siap Hedge) | Alternatif O/U:_ {m['mkts']['alt_over_str']}"
            else:
                pick, odds, prob = f"*{opt_2way_ou['name']}*", opt_2way_ou["odds"], opt_2way_ou["safe"]
                hedge_label = "Total Over (2.5) Gol" if opt_2way_ou["type"] == "under" else "Total Under (1.5) Gol"
                alt_str = m["mkts"]["alt_under_str"] if opt_2way_ou["type"] == "under" else m["mkts"]["alt_over_str"]
                alt_line_note = f"   ↳ _Anchor 2-Arah Murni (Siap Hedge) | Garis Lain:_ {alt_str}"
        else:
            if not m["is_trap"] and m["max_p"] >= 0.46:
                pick, odds, prob = f"*{m['fav_pick']}* (1X2 Mutlak)", m["fav_odds"], m["max_p"]
                hedge_label = "X2" if m["fav_pick"] == "W1" else "1X"
                alt_line_note = f"   ↳ _Alternatif O/U:_ {m['mkts']['alt_over_str']}"
            else:
                if m["is_cup"] or m["px"] >= 0.285:
                    opt = m["mkts"]["best_under"]
                    hedge_label = f"Total Over ({opt['line']}) Gol"
                    alt_line_note = f"   ↳ _Garis Under Lain di 1xBet:_ {m['mkts']['alt_under_str']}"
                else:
                    opt = m["mkts"]["best_over"]
                    hedge_label = f"Total Under ({opt['line']}) Gol"
                    alt_line_note = f"   ↳ _Garis Over Lain di 1xBet:_ {m['mkts']['alt_over_str']}"
                pick, odds, prob = f"*{opt['name']}*", opt["odds"], opt["safe"]

        m_odds *= odds
        m_probs.append(prob)
        hedge_opp_odds = round(0.935 / max(0.05, (1.0 - prob)), 2)
        if is_last_leg:
            last_leg_info = {
                "name": m["name"], "time": m["datetime"], "pick": pick,
                "odds": odds, "h_label": hedge_label, "h_odds": hedge_opp_odds
            }

        out.append(f"{i}. {t_str}{m['name']} ➡️ {pick} (`@{odds:.3f}` | Safe: `{prob*100:.1f}%`)\n{alt_line_note}")

    m_win_prob = float(np.prod(m_probs))
    m_miss1_prob = calc_heartbreak_prob(m_probs)
    out.append(
        f"💰 *Est. Total Odds:* `~{m_odds:.2f}x` (Modal Rp{modal_int:,} ➡️ *Rp{int(modal_int*m_odds):,}*)\n"
        f"📈 *Survival/Win Rate:* `{m_win_prob*100:.2f}%` (`{int(m_win_prob*1000)}/1000`) | "
        f"⚠️ *Risiko Meleset 1 Tim ({actual_legs-1}/{actual_legs}):* `{m_miss1_prob*100:.2f}%`"
    )

    # -----------------------------------------------------------------
    # SLIP 2: 1xBET RESULT + TOTAL COMBO BOOSTER
    # -----------------------------------------------------------------
    out.append(f"\n⚡ *SLIP 2: 1xBET RESULT + TOTAL COMBO BOOSTER ({actual_legs} TIM)*")
    c_odds, c_probs = 1.0, []
    for i, m in enumerate(selected_chrono, 1):
        t_str = f"`[{m['datetime']}]` " if m["datetime"] != "99:99" else ""
        if not m["is_trap"] and m["max_p"] >= 0.46:
            pick, odds, prob = f"*{m['fav_pick']}* (1X2 Mutlak)", m["fav_odds"], m["max_p"]
        else:
            opt = m["mkts"]["dc_u35"] if (m["is_cup"] or m["px"] >= 0.285) else m["mkts"]["dc_o15"]
            pick, odds, prob = f"*{opt['name']}*", opt["odds"], opt["safe"]
        c_odds *= odds
        c_probs.append(prob)
        out.append(f"{i}. {t_str}{m['name']} ➡️ {pick} (`@{odds:.3f}` | Win: `{prob*100:.1f}%`)")

    c_win_prob = float(np.prod(c_probs))
    out.append(
        f"💰 *Est. Total Odds:* `~{c_odds:.2f}x` (Modal Rp{modal_int:,} ➡️ *Rp{int(modal_int*c_odds):,}*)\n"
        f"📈 *Win Rate Simulasi:* `{c_win_prob*100:.2f}%` (`{int(c_win_prob*1000)}/1000`)"
    )

    # -----------------------------------------------------------------
    # SLIP 3: HIGH-YIELD JACKPOT BOOSTER (Strength-First 100x Escalator)
    # -----------------------------------------------------------------
    out.append(f"\n🚀 *SLIP 3: HIGH-YIELD JACKPOT BOOSTER ({actual_legs} TIM)*")
    j_picks = []
    for m in selected_chrono:
        if m["max_p"] >= 0.72:
            opt = m["mkts"]["hdp_15"]
            j_picks.append({"m": m, "pick": f"*{opt['name']}*", "odds": opt["odds"], "prob": opt["win"], "upgraded": True})
        elif m["max_p"] >= 0.52 and not m["is_cup"]:
            opt = m["mkts"]["hdp_10"] if m["mkts"]["hdp_10"]["odds"] >= m["mkts"]["win_o15"]["odds"] else m["mkts"]["win_o15"]
            j_picks.append({"m": m, "pick": f"*{opt['name']}*", "odds": opt["odds"], "prob": opt.get("safe", opt["win"]), "upgraded": True})
        else:
            j_picks.append({"m": m, "pick": f"*{m['fav_pick']}* (1X2 Mutlak)", "odds": m["fav_odds"], "prob": m["max_p"], "upgraded": False})

    if actual_legs >= 5:
        upgrade_order = sorted(range(len(j_picks)), key=lambda idx: j_picks[idx]["m"]["max_p"], reverse=True)
        for idx in upgrade_order:
            curr_total = float(np.prod([x["odds"] for x in j_picks]))
            if curr_total >= 95.0:
                break
            item = j_picks[idx]
            if not item["upgraded"] and not item["m"]["is_cup"]:
                opt = item["m"]["mkts"]["win_o15"]
                item["pick"] = f"*{opt['name']}*"
                item["odds"] = opt["odds"]
                item["prob"] = opt["win"]
                item["upgraded"] = True

    j_odds, j_probs = 1.0, []
    for i, item in enumerate(j_picks, 1):
        m = item["m"]
        t_str = f"`[{m['datetime']}]` " if m["datetime"] != "99:99" else ""
        j_odds *= item["odds"]
        j_probs.append(item["prob"])
        out.append(f"{i}. {t_str}{m['name']} ➡️ {item['pick']} (`@{item['odds']:.3f}` | Win: `{item['prob']*100:.1f}%`)")

    j_win_prob = float(np.prod(j_probs))
    j_miss1_prob = calc_heartbreak_prob(j_probs)
    out.append(
        f"💰 *Est. Total Odds:* `~{j_odds:.2f}x` (Modal Rp{modal_int:,} ➡️ *Rp{int(modal_int*j_odds):,}*)\n"
        f"📈 *Full Win Rate:* `{j_win_prob*100:.2f}%` (`{int(j_win_prob*1000)}/1000`) | "
        f"⚠️ *Peluang Tembus {actual_legs-1}/{actual_legs}:* `{j_miss1_prob*100:.2f}%` (`{int(j_miss1_prob*1000)}/1000`)"
    )

    # -----------------------------------------------------------------
    # KALKULATOR HEDGING 2-ARAH MURNI & SYSTEM BET
    # -----------------------------------------------------------------
    pot_win_1 = modal_int * m_odds
    h_odds_safe = max(1.25, last_leg_info.get("h_odds", 2.50))
    hedge_stake = int(round(pot_win_1 / h_odds_safe))
    guaranteed_net = int(round(pot_win_1 - modal_int - hedge_stake))

    out.append(f"\n🛡️ *KALKULATOR HEDGING 2-ARAH & ANTI-PATAH HATI 1xBET:*")
    if actual_legs >= 2 and guaranteed_net > 0:
        out.append(
            f"1️⃣ *Kunci Profit Laga Terakhir (Slip 1 — 100% Bebas Celah Half-Loss/Void):*\n"
            f"   Laga penutup *{last_leg_info['name']}* (`{last_leg_info['time']}`) dikunci pada pasar 2-arah murni terbaik ({last_leg_info['pick']}).\n"
            f"   Jika {actual_legs-1} laga awal tembus semua:\n"
            f"   • *Opsi A:* Klik **Sell Bet Slip (Cash Out)** di menu History 1xBet.\n"
            f"   • *Opsi B (Manual Hedge):* Pasang *Single Bet* pada **{last_leg_info['h_label']}** (Est. Odds `~{h_odds_safe}`) "
            f"sebesar **Rp{hedge_stake:,}**. Hasil apapun di laga penutup, Anda mengunci **Profit Bersih Pasti ~Rp{guaranteed_net:,}**!"
        )
    if actual_legs >= 4:
        ratio_miss = j_miss1_prob / max(1e-6, j_win_prob)
        out.append(
            f"2️⃣ *Taktik System {actual_legs-1}/{actual_legs} (Khusus Slip 3 Jackpot):*\n"
            f"   Peluang meleset 1 tim di Slip 3 (`{j_miss1_prob*100:.1f}%`) adalah **{ratio_miss:.1f}x lebih sering terjadi** daripada sapu bersih. "
            f"Ubah tipe taruhan di atas Bet Slip 1xBet dari `Accumulator` menjadi **`System {actual_legs-1}/{actual_legs}`** agar tetap gajian meski terpeleset 1 tim."
        )

    return "\n".join(out)


# =====================================================================
# 5. CLI / TOOL HANDLER
# =====================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Hermes 1xBet Quantitative Parlay Engine v7.1 Final")
    parser.add_argument("json_input", nargs="?", help="JSON string daftar pertandingan atau path ke file .json")
    parser.add_argument("--legs", type=int, default=7, help="Jumlah tim fleksibel (default: 7)")
    parser.add_argument("--modal", type=int, default=10000, help="Modal taruhan Rupiah (default: 10000)")
    parser.add_argument("--schema", action="store_true", help="Cetak Tool Schema JSON untuk Hermes")

    args = parser.parse_args()

    if args.schema:
        print(json.dumps(TOOL_SCHEMA, indent=2))
        sys.exit(0)

    if not args.json_input:
        print("Gunakan: python3 hermes_1xbet_quant_v71.py '[{\"name\":\"Tim A vs B\",\"datetime\":\"19.11 06:30\",\"w1\":1.5,\"x\":4.0,\"w2\":6.0}]' --legs 5 --modal 10000")
        sys.exit(1)

    raw_arg = args.json_input
    try:
        if raw_arg.endswith(".json"):
            with open(raw_arg, "r", encoding="utf-8") as f:
                raw_arg = f.read()
    except Exception:
        pass

    print(run_1xbet_parlay_engine(raw_arg, target_legs=args.legs, modal=args.modal))