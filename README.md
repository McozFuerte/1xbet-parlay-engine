# ⚽ 1xBet Quantitative Parlay Engine v7.1

**Hermes Agent skill** — analisa parlay sepak bola kuantitatif dari screenshot odds 1xBet.
Zero hand-calculation: semua probabilitas & odds dihitung engine, output verbatim.

![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![status](https://img.shields.io/badge/status-production-brightgreen)

---

## 🧠 Apa yang dikerjakan engine

| Komponen | Fungsi |
|---|---|
| **Shin's Method** | Buang margin bookmaker dari odds 1X2 (Newton-Raphson, koreksi bias underdog/seri) |
| **Dixon-Coles 10×10** | Matriks skor penuh + koreksi rho (0-0, 1-0, 0-1, 1-1) — sumber semua pasar turunan |
| **Aktuaria Asian O/U** | Harga eksak garis O/U & Handicap (half-win / half-loss / push, vig kondisional 0.935) |
| **Monte Carlo 10.000×** | Simulasi per laga + frequency empiris |
| **Trap Detection** | JEBAKAN = favorit < 43.5% ATAU entropi > 1.545 (coin-flip) → wajib dibuang |
| **3 Slip Recipes** | Tactical (2-way anchor + hedge) / Combo Booster / Jackpot Escalator (System N-1/N) |
| **Layer 2** | Cross-check berita & form via web search: cedera, rotasi/motivasi, tren 5 laga |

## 🚀 Cara pakai

```bash
python3 scripts/parlay_engine.py '[
  {"name":"Team A vs Team B","datetime":"25.11 03:00","w1":1.459,"x":5.03,"w2":7.6,"is_cup":false}
]' --legs 10 --modal 10000
```

**Input per laga:** `w1/x/w2` (odds 1X2), `datetime` (`DD.MM HH:MM`), `is_cup` (piala domestik = true),
opsional `avail_ou` + `real_o15_odds` kalau garis O/U kelihatan di bet slip.

Duplikat antar-screenshot auto-dedup (token Jaccard), kick-off 23:xx/02:xx dihandle
midnight-rollover, laga odds kepotong di edge layar wajib dibuang saat ekstraksi.

## 📊 Contoh output (UCL Tour 5, Nov 2026)

| Slip | Profil | Odds | Win rate (MC) |
|---|---|---|---|
| 1 Tactical | 🟢 aman, anchor O/U + hedge | 10.44x | 8.51% |
| 2 Combo | 🟡 medium, 1X2 murni | 13.39x | 7.05% |
| 3 Jackpot | 🔴 hard, handicap escalator | 171.84x | 3.04% |

```
🎯 SLIP 1: TACTICAL MEDIUM RISK (10 TIM)
...
💰 Est. Total Odds: ~10.44x (Modal Rp10,000 ➡️ Rp104,363)
📈 Survival/Win Rate: 8.51% (85/1000) | ⚠️ Risiko Meleset 1 Tim (9/10): 24.34%

🛡️ KALKULATOR HEDGING 2-ARAH:
   • Opsi A: Sell Bet Slip (Cash Out)
   • Opsi B: Single bet lawan anchor → PROFIT BERSIH PASTI ~Rp80,202
```

## 🔍 Layer 2 — Fundamental Cross-Check

Setelah engine jalan, tim di slip di-cross-check via web search:

- 🔑 Key injuries/suspensions (striker, playmaker, kiper inti)
- 🔄 Motivation & rotation trap (udah lolos grup / main 2-3 hari lalu)
- 📉 Recent form (favorit yang lagi kalah beruntun)

Mode: **default** (cuma banker + anchor) · **deep** (semua tim) · **fast** (skip).

```
🔍 AUDIT FUNDAMENTAL (BERITA & FORM):
- Real Madrid: ✅ AMAN — bebas cedera, PSV baru kalah 1-2
- RB Leipzig: 🚨 RED FLAG — rating lawan lebih tinggi ➡️ ganti leg
```

## 📁 Struktur

```
├── SKILL.md                          # workflow lengkap untuk Hermes Agent
├── scripts/parlay_engine.py          # engine utama v7.1
├── scripts/simulate_parlay.py        # verifier MC + konverter odds + --combine
└── references/                       # detail placement automation (bebas kredensial)
```

## ⚠️ Disclaimer

- Parlay = struktur **minus-EV** (margin 1.5%/leg majemuk ~14% untuk 10 leg).
  Engine selalu menampilkan combined win probability bersama combined odds —
  lihat trade-off-nya secara jujur, bukan cuma multiplier-nya.
- Odds handicap = estimasi aktuaria → cocokkan ke garis nyata bookmaker sebelum pasang.
- Model odds-only: tidak melihat line-up final & motivasi jangka pendek (itu tugas Layer 2).
- BET GUARD: jangan pernah pasang slip dengan jumlah leg < target.
- 18+, bertanggung jawab atas keputusan taruhan sendiri.

## License

MIT
