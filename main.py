import os
import json
import pandas as pd
import yfinance as yf
import requests

# ==========================================
# 1. KONFIGURATION & KONSTANTER
# ==========================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
HOLDINGS_FILE = "holdings.json"

# Tröskelvärde för courtage/växlingsavgift (i procentenheter momentum)
SWEDISH_SWAP_THRESHOLD = 1.0  # 1.0% diff för svenska aktier
NORDIC_SWAP_THRESHOLD = 1.5   # 1.5% diff för norska/danska aktier (0.5% valutaväxling t/r)

# Universum
SWEDISH_STOCKS = [
    "VOLV-B.ST", "INVE-B.ST", "ERIC-B.ST", "AZN.ST", "SEB-A.ST", 
    "SAND.ST", "ATCO-A.ST", "SHB-A.ST", "SWED-A.ST", "HM-B.ST",
    "ABB.ST", "TELIA.ST", "ALFA.ST", "ASSA-B.ST", "EVO.ST",
    "BOL.ST", "SKA-B.ST", "SKF-B.ST", "NIBE-B.ST", "SAAB-B.ST", "HEXA-B.ST"
]
NORWEGIAN_STOCKS = ["EQNR.OL", "DNB.OL", "TEL.OL", "MOWI.OL", "YAR.OL", "AKRBP.OL"]
DANISH_STOCKS = ["NOVO-B.CO", "MAERSK-B.CO", "DSV.CO", "ORSTED.CO", "CARL-B.CO"]

ALL_STOCKS = SWEDISH_STOCKS + NORWEGIAN_STOCKS + DANISH_STOCKS
INDEX_TICKER = "^OMX"
CURRENCIES = ["NOKSEK=X", "DKKSEK=X"]

# ==========================================
# 2. HJÄLPFUNKTIONER
# ==========================================
def load_holdings():
    if os.path.exists(HOLDINGS_FILE):
        try:
            with open(HOLDINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Fel vid inläsning av {HOLDINGS_FILE}: {e}")
    return {"cash_sek": 10000.0, "stock_positions": {}, "markets_position": None}

def save_holdings(data):
    with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Fel: Telegram-nycklar saknas i miljövariablerna.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    try:
        resp = requests.post(url, json=payload)
        resp.raise_for_status()
        print("Signal skickad till Telegram!")
    except Exception as e:
        print(f"Telegram-fel: {e}")

# ==========================================
# 3. HÄMTA MARKNADSDATA & VALUTOR (RENSAD FRÅN NAN)
# ==========================================
state = load_holdings()
all_tickers = ALL_STOCKS + [INDEX_TICKER] + CURRENCIES

# Hämta data och fyll i tidsluckor/helgdagar automatiskt
raw_data = yf.download(all_tickers, period="1y")["Close"]
data = raw_data.ffill().bfill()

# Valutakurser för konvertering till SEK
nok_sek = data["NOKSEK=X"].dropna().iloc[-1] if "NOKSEK=X" in data else 1.0
dkk_sek = data["DKKSEK=X"].dropna().iloc[-1] if "DKKSEK=X" in data else 1.45

def get_price_in_sek(ticker):
    price_series = data[ticker].dropna()
    if price_series.empty:
        return 0.0
    price = price_series.iloc[-1]
    if ticker.endswith(".OL"):
        return price * nok_sek
    elif ticker.endswith(".CO"):
        return price * dkk_sek
    return price

# ==========================================
# 4. RÄKNA UT TOTALT PORTFÖLJVÄRDE
# ==========================================
stock_positions = state.get("stock_positions", {})
markets_position = state.get("markets_position", None)
cash_sek = state.get("cash_sek", 10000.0)

# Värdera aktier i SEK
stocks_value_sek = 0.0
for ticker, shares in stock_positions.items():
    if ticker in data:
        stocks_value_sek += shares * get_price_in_sek(ticker)

# Värdera Avanza Markets derivat
markets_value_sek = 0.0
if markets_position:
    markets_value_sek = markets_position.get("value_sek", 0.0)

total_portfolio_value = cash_sek + stocks_value_sek + markets_value_sek

# Allokering (77.5% Aktier, 22.5% Derivat)
stocks_allocation_total = total_portfolio_value * 0.775
markets_allocation_total = total_portfolio_value * 0.225
per_stock_target_sek = stocks_allocation_total / 4.0

# ==========================================
# 5. MODELL 1: NORDISK AKTIESTRATEGI (COURTAGEOPTIMERAD)
# ==========================================
# Säkerställ ren dataserie för OMX utan tomma rader
omx = data[INDEX_TICKER].dropna()
omx_ma200 = omx.rolling(window=200).mean()
market_is_bullish = omx.iloc[-1] > omx_ma200.iloc[-1]

stock_data = data[ALL_STOCKS]
momentum = (stock_data.iloc[-1] / stock_data.iloc[-60] - 1) * 100

current_stock_list = list(stock_positions.keys())
final_stock_list = []

if market_is_bullish:
    ranked_stocks = momentum.sort_values(ascending=False)
    candidates = list(ranked_stocks.index)
    
    for candidate in candidates:
        if len(final_stock_list) >= 4:
            break
            
        if candidate in current_stock_list:
            final_stock_list.append(candidate)
        else:
            should_add = True
            cand_score = ranked_stocks[candidate]
            threshold = NORDIC_SWAP_THRESHOLD if (candidate.endswith(".OL") or candidate.endswith(".CO")) else SWEDISH_SWAP_THRESHOLD
            
            for held in current_stock_list:
                if held not in final_stock_list:
                    held_score = ranked_stocks.get(held, -999)
                    if cand_score < (held_score + threshold):
                        should_add = False
                        break
            
            if should_add or len(current_stock_list) < 4:
                final_stock_list.append(candidate)

    for candidate in candidates:
        if len(final_stock_list) >= 4:
            break
        if candidate not in final_stock_list:
            final_stock_list.append(candidate)
else:
    final_stock_list = []

# ==========================================
# 6. MODELL 2: AVANZA MARKETS DERIVAT (MINI FUTURES)
# ==========================================
omx_ma20 = omx.rolling(window=20).mean()
short_term_bullish = omx.iloc[-1] > omx_ma20.iloc[-1]

markets_signal = "KASSA"
markets_target_val = 0.0

if market_is_bullish and short_term_bullish:
    markets_target_val = max(1000.0, round(markets_allocation_total, -1))
    markets_signal = f"KÖP MINI L OMX AVA (Hävstång ~2x-4x) för ~{markets_target_val:.0f} kr"
elif not market_is_bullish and not short_term_bullish:
    markets_target_val = max(1000.0, round(markets_allocation_total, -1))
    markets_signal = f"KÖP MINI S OMX AVA (Hävstång ~2x-3x) för ~{markets_target_val:.0f} kr"
else:
    markets_signal = "LIGG I KASSA (Ingen tydlig kort trend)"

# ==========================================
# 7. GENERERA TELEGRAM-MEDDELANDE
# ==========================================
msg = "📊 *DAGLIG HANDELSSIGNAL*\n"
msg += f"💰 *Totalt Portföljvärde:* ~{total_portfolio_value:.0f} SEK\n\n"

msg += "--- 📈 *1. NORDISKA AKTIER (77.5%)* ---\n"
if market_is_bullish:
    msg += "🟢 *Marknadsstatus:* BULL (OMXS30 > MA200)\n\n"
    
    to_sell = [t for t in current_stock_list if t not in final_stock_list]
    to_buy = [t for t in final_stock_list if t not in current_stock_list]
    to_hold = [t for t in final_stock_list if t in current_stock_list]

    if to_sell:
        msg += "🔴 *SÄLJ:* \n" + "\n".join([f"• {t}" for t in to_sell]) + "\n\n"
    if to_buy:
        msg += "🟢 *KÖP:* \n"
        for t in to_buy:
            score = momentum[t]
            msg += f"• *{t}* (~{per_stock_target_sek:.0f} kr) | Mom: +{score:.1f}%\n"
        msg += "\n"
    if to_hold:
        msg += "🔵 *BEHÅLL:* \n" + "\n".join([f"• {t}" for t in to_hold]) + "\n\n"
    if not to_buy and not to_sell:
        msg += "✅ *Inga ändringar krävs. Håll nuvarande aktier.*\n\n"
else:
    msg += "🔴 *Marknadsstatus:* BEAR (OMXS30 < MA200)\n"
    msg += "⚠️ *SÄLJ ALLA AKTIER OGÅENDE OCH GÅ TILL KASSA.*\n\n"

msg += "--- ⚡ *2. AVANZA MARKETS DERIVAT (22.5%)* ---\n"
msg += f"💡 *Signal:* {markets_signal}\n"
msg += "ℹ️ *Courtageregel:* Order > 1 000 kr är helt courtagefria.\n"

# ==========================================
# 8. SPARA TILLSTÅND OCH SKICKA
# ==========================================
new_stock_positions = {}
for t in final_stock_list:
    price_sek = get_price_in_sek(t)
    shares = round(per_stock_target_sek / price_sek) if price_sek > 0 else 0
    new_stock_positions[t] = shares

state["stock_positions"] = new_stock_positions
if "MINI" in markets_signal:
    state["markets_position"] = {"type": markets_signal.split(" för")[0], "value_sek": markets_target_val}
else:
    state["markets_position"] = None

state["cash_sek"] = max(0.0, total_portfolio_value - (len(final_stock_list) * per_stock_target_sek) - markets_target_val)

save_holdings(state)
send_telegram_message(msg)
