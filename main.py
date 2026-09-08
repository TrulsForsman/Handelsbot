import os
import pandas as pd
import yfinance as yf
import requests

# 1. HÄMTA BOT-TOKEN & CHAT-ID SÄKERT FRÅN MILJÖVARIABLER
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Fel: TELEGRAM_TOKEN eller TELEGRAM_CHAT_ID saknas i miljövariablerna.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Signal skickad till Telegram!")
    except Exception as e:
        print(f"Fel vid sändning till Telegram: {e}")

# 2. HÄMTA DATA & ANALYSERA
tickers = ["VOLV-B.ST", "ERIC-B.ST", "INVE-B.ST", "AZN.ST", "SEB-A.ST", "SAND.ST", "ATCO-A.ST"]
index_ticker = "^OMX"

data = yf.download(tickers + [index_ticker], period="1y")["Close"]

omx = data[index_ticker]
omx_ma200 = omx.rolling(window=200).mean()
market_is_bullish = omx.iloc[-1] > omx_ma200.iloc[-1]

# 3. BYGG MEDDELANDE
message = "📊 *DAGLIG HANDELSSIGNAL*\n\n"

if market_is_bullish:
    message += "🟢 *Marknadsstatus:* BULL (OMXS30 > MA200)\n\n"
    message += "*Topp 4 aktier att köpa/inneha:*\n"
    
    stock_data = data[tickers]
    momentum = (stock_data.iloc[-1] / stock_data.iloc[-60] - 1) * 100
    top_stocks = momentum.sort_values(ascending=False).head(4)
    
    for ticker, score in top_stocks.items():
        clean_ticker = ticker.replace(".ST", "")
        message += f"• *{clean_ticker}*: Momentum +{score:.2f}%\n"
        
    message += "\n💡 *Åtgärd:* Allokera ~2 500 kr per position på Avanza."
else:
    message += "🔴 *Marknadsstatus:* BEAR (OMXS30 < MA200)\n\n"
    message += "⚠️ *Åtgärd:* Gå till 100% likviditet/kassa. Inga nya köp."

# 4. SKICKA SIGNAL
send_telegram_message(message)
