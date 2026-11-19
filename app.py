import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

st.set_page_config(page_title="AI Trading Assistant", page_icon="📈", layout="wide")

DEFAULT_TICKERS = "AAPL, MSFT, NVDA, AMZN, META, GOOGL, TSLA, AVGO, JPM, COST, AMD, NFLX, SPY, QQQ"
WATCHLIST_PATH = Path(__file__).resolve().with_name("moje_tickery.txt")


def load_watchlist():
    try:
        return WATCHLIST_PATH.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return DEFAULT_TICKERS
    except (OSError, UnicodeError):
        st.session_state.watchlist_error = "Uložený seznam se nepodařilo načíst. Zobrazuji výchozí tickery."
        return DEFAULT_TICKERS


def save_watchlist():
    temporary_path = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=WATCHLIST_PATH.parent, delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(st.session_state.watchlist)
        temporary_path.replace(WATCHLIST_PATH)
    except OSError:
        st.session_state.watchlist_error = "Seznam se nepodařilo uložit do složky aplikace."
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
    else:
        st.session_state.pop("watchlist_error", None)


if "watchlist" not in st.session_state:
    st.session_state.watchlist = load_watchlist()

st.title("📈 AI Trading Assistant v2.0")
st.caption("Denní skener amerických akcií • pouze analytický/paper režim • žádné obchodní příkazy")

with st.sidebar:
    st.header("Nastavení")
    tickers_text = st.text_area("Seznam tickerů", key="watchlist", height=160, on_change=save_watchlist)
    st.caption(
        "Tickery odděluj čárkou nebo novým řádkem. "
        "Seznam se uloží, když po úpravě klikneš mimo pole."
    )
    if st.session_state.get("watchlist_error"):
        st.warning(st.session_state.watchlist_error)
    period = st.selectbox("Historie", ["1y", "2y", "5y"], index=1)
    refresh = st.button("Načíst data a analyzovat", type="primary", width="stretch")

    with st.expander("Kapitál a riziko"):
        capital = st.number_input("Obchodní kapitál (USD)", min_value=100.0, max_value=1_000_000.0, value=2500.0, step=100.0)
        risk_pct = st.number_input("Riziko na obchod (%)", 0.0, 100.0, 2.0, step=0.1, format="%.2f")
        daily_limit_pct = st.number_input("Denní limit ztráty (%)", 0.0, 100.0, 4.0, step=0.1, format="%.2f")
        weekly_limit_pct = st.number_input("Týdenní limit ztráty (%)", 0.0, 100.0, 6.0, step=0.1, format="%.2f")
        st.caption("Napiš procento a potvrď Enterem. Pro desetinná místa použij tečku, například 1.25.")

st.info(
    "Yahoo Finance poskytuje denní svíčky přes yfinance. Ceny i zprávy mohou být opožděné nebo neúplné. "
    "Denní svíčka během seance může být předběžná. Uvedené úrovně jsou modelové a aplikace funguje pouze pro analýzu."
)

st.subheader("Rizikový rozpočet")
risk_usd = capital * risk_pct / 100
daily_limit_usd = capital * daily_limit_pct / 100
weekly_limit_usd = capital * weekly_limit_pct / 100
position_limit_usd = min(risk_usd, daily_limit_usd, weekly_limit_usd)
c1, c2, c3 = st.columns(3)
c1.metric("Riziko na obchod", f"${risk_usd:,.2f}")
c2.metric("Denní limit ztráty", f"${daily_limit_usd:,.2f}")
c3.metric("Týdenní limit ztráty", f"${weekly_limit_usd:,.2f}")
st.caption(
    f"Limit rizika pro jednu modelovou pozici je ${position_limit_usd:,.2f}, nejnižší ze tří nastavených hodnot. "
    "Výpočet posuzuje každý titul samostatně a počítá s plnými limity před případnými ztrátami."
)

def calc_indicators(df):
    df = df.dropna(subset=["High", "Low", "Close"]).copy()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = -delta.clip(upper=0).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
    df["RSI14"] = rsi.mask((loss == 0) & (gain == 0), 50.0)
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - prev_close).abs(),
        (df["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    df["ATR14"] = tr.rolling(14).mean()
    df["VOL20"] = df["Volume"].rolling(20).mean()
    df["HIGH20_PREV"] = df["High"].shift(1).rolling(20).max()
    return df

@st.cache_data(ttl=300, max_entries=128, show_spinner=False)
def load_prices(symbol, period):
    ticker = yf.Ticker(symbol)
    data = ticker.history(period=period, interval="1d", auto_adjust=False, timeout=10)
    metadata = {}
    if not data.empty:
        try:
            source = ticker.history_metadata
            metadata = {key: source.get(key) for key in ("longName", "shortName", "currency")}
        except Exception:
            pass
    return data, metadata


def article_url(*values):
    for value in values:
        if not isinstance(value, str) or any(char.isspace() for char in value):
            continue
        try:
            parts = urlsplit(value)
            if parts.scheme in {"https", "http"} and parts.hostname and not parts.username:
                return value
        except ValueError:
            continue
    return None


@st.cache_data(ttl=900, max_entries=128, show_spinner=False)
def load_news(symbol):
    articles = []
    seen = set()
    for item in yf.Ticker(symbol).news or []:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, dict):
            content = item
        title = content.get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        canonical = content.get("canonicalUrl")
        click = content.get("clickThroughUrl")
        url = article_url(
            canonical.get("url") if isinstance(canonical, dict) else None,
            click.get("url") if isinstance(click, dict) else None,
            content.get("link"),
        )
        article_id = url or title
        if article_id in seen:
            continue
        seen.add(article_id)
        provider = content.get("provider")
        publisher = provider.get("displayName") if isinstance(provider, dict) else None
        published = pd.to_datetime(content.get("pubDate"), errors="coerce", utc=True)
        if pd.isna(published):
            published = pd.to_datetime(
                content.get("providerPublishTime"), unit="s", errors="coerce", utc=True,
            )
        articles.append((title, publisher or content.get("publisher"), published, url))
    articles.sort(key=lambda article: (
        pd.notna(article[2]), 0 if pd.isna(article[2]) else article[2].timestamp()
    ), reverse=True)
    return articles[:5]


def scenario(df, trend):
    if trend != "Rostoucí":
        return None, None, None, None, "Model nákupní pozice vyžaduje rostoucí trend."

    last = df.iloc[-1]
    atr = last["ATR14"]
    if not np.isfinite(atr) or atr <= 0:
        return None, None, None, None, "Pro výpočet úrovní chybí použitelná hodnota ATR."

    if last["Close"] > last["HIGH20_PREV"]:
        entry = last["HIGH20_PREV"]
        condition = "Vstup odpovídá návratu k proraženému maximu 20 seancí a odrazu nad něj."
    else:
        entry = last["EMA20"]
        condition = "Vstup odpovídá návratu k EMA20 a potvrzenému odrazu nad ni při trvajícím růstovém trendu."

    stop = entry - 2 * atr
    if stop <= 0:
        return None, None, None, None, "Stop podle 2× ATR vychází mimo kladné ceny."

    # Local peaks require a lower high on each side. Use confirmed peaks only.
    highs = df["High"].tail(252)
    peaks = highs[(highs > highs.shift(1)) & (highs > highs.shift(-1))]
    resistance = peaks[peaks > max(entry, last["Close"])].min()
    if pd.notna(resistance):
        target = resistance
        condition += " Cíl odpovídá nejbližšímu potvrzenému vrcholu nad vstupem i cenou."
    elif last["Close"] > last["HIGH20_PREV"]:
        prior_range = df.iloc[-21:-1]
        target = entry + (prior_range["High"].max() - prior_range["Low"].min())
        if target <= last["Close"]:
            return entry, stop, None, None, condition + " Cena už dosáhla projekce rozpětí."
        condition += " Cíl je projekce výšky rozpětí předchozích 20 seancí nad průraz."
    else:
        return entry, stop, None, None, condition + " Vyšší potvrzený vrchol nebyl nalezen."

    return entry, stop, target, (target - entry) / (entry - stop), condition


def analyze(ticker, period):
    try:
        raw, metadata = load_prices(ticker, period)
    except Exception:
        raw, metadata = pd.DataFrame(), {}
    name = metadata.get("longName") or metadata.get("shortName")
    currency = metadata.get("currency")
    result = {
        "Ticker": ticker, "Název": name, "Měna": currency,
        "Cena": None, "Datum dat": None, "ATR14": None, "Trend": "Nedostupný",
        "Vstup": None, "Stop-loss": None, "Cíl": None, "R:R": None,
        "Skóre": None, "Stav": "Bez dat", "Důvody": "Denní ceny se nepodařilo načíst.",
    }
    if raw.empty or "Close" not in raw:
        return result
    raw = raw.sort_index().replace([np.inf, -np.inf], np.nan)
    prices = raw["Close"].dropna()
    if prices.empty:
        return result
    close = float(prices.iloc[-1])
    result.update({"Cena": close, "Datum dat": prices.index[-1].strftime("%Y-%m-%d")})
    if not {"High", "Low"}.issubset(raw.columns):
        result.update(Stav="Neúplná data", Důvody="V historii chybí denní maxima nebo minima.")
        return result
    if "Volume" not in raw:
        raw["Volume"] = np.nan
    df = calc_indicators(raw)
    if df.empty or df.index[-1] != prices.index[-1]:
        result.update(Stav="Neúplná data", Důvody="Poslední denní svíčka nemá maximum nebo minimum.")
        return result
    x = df.iloc[-1]
    result.update(ATR14=x["ATR14"], RSI=x["RSI14"])
    if len(df) < 200:
        result.update(Stav="Krátká historie", Důvody="Pro vyhodnocení trendu chybí 200 denních svíček.")
        return result
    atr = float(x["ATR14"])
    rsi = float(x["RSI14"])
    ema20, ema50, ema200 = float(x["EMA20"]), float(x["EMA50"]), float(x["EMA200"])
    vol_ratio = float(x["Volume"] / x["VOL20"]) if x["VOL20"] else np.nan
    breakout = close > float(x["HIGH20_PREV"])
    trend = close > ema50 > ema200
    pullback = trend and close >= ema20 * 0.98 and close <= ema20 * 1.02 and rsi >= 45
    score = 0
    reasons = []
    if trend:
        score += 2; reasons.append("rostoucí trend (cena > EMA50 > EMA200)")
    if breakout:
        score += 2; reasons.append("průlom maxima předchozích 20 seancí")
    if pullback:
        score += 1; reasons.append("návrat poblíž EMA20 v rostoucím trendu")
    if 50 <= rsi <= 68:
        score += 1; reasons.append("RSI v neutrálně-růstovém pásmu")
    if vol_ratio >= 1.3:
        score += 1; reasons.append("objem nad 20denním průměrem")
    if rsi > 75:
        reasons.append("varování: RSI nad 75 – možná překoupenost")
    if not reasons:
        reasons.append("zatím bez jasné shody sledovaných podmínek")
    stop = close - 2 * atr
    status = "SLEDOVAT" if score >= 4 else ("ČEKAT" if score >= 2 else "ŽÁDNÝ SIGNÁL")
    trend_label = "Rostoucí" if trend else "Neutrální"
    if close < ema50 < ema200:
        trend_label = "Klesající"
    entry, entry_stop, target, reward_to_risk, condition = scenario(df, trend_label)
    result.update({
        "Trend": trend_label, "Vstup": entry, "Stop-loss": entry_stop, "Cíl": target,
        "R:R": reward_to_risk, "Podmínka vstupu": condition,
        "Skóre": score, "Stav": status, "Stop model od poslední ceny": stop if close > stop > 0 else None,
        "EMA20": ema20, "EMA50": ema50, "EMA200": ema200,
        "Objem / průměr": vol_ratio, "Důvody": ", ".join(reasons),
    })
    return result


def price_label(value, currency):
    if pd.isna(value):
        return "—"
    price = f"{value:,.4f}" if 0 < abs(value) < 1 else f"{value:,.2f}"
    return f"{price} {currency}" if pd.notna(currency) and currency else price


def size_position(row, capital, risk_limit):
    close = row["Cena"]
    stop = row.get("Stop model od poslední ceny")
    shares = value = loss = None
    if row["Měna"] == "USD" and pd.notna(close) and pd.notna(stop) and close > stop > 0:
        risk_per_share = max(close - stop, 0.01)
        shares = min(int(risk_limit / risk_per_share), int(capital / close))
        value = shares * close
        loss = shares * (close - stop)
    return {
        **row,
        "Akcie dle rizika a hotovosti": shares,
        "Hodnota pozice (USD)": value,
        "Modelová ztráta při stopu (USD)": loss,
    }


TREND_COLORS = {
    "Rostoucí": ("#09653e", "#eef9f4"),
    "Klesající": ("#a51e32", "#fff1f3"),
    "Neutrální": ("#000000", "#fff8e9"),
}

CARD_STYLES = """
<style>
.ticker-summary {
    border-radius: .5rem; padding: .75rem; color: #20283c;
    font-size: .875rem; overflow-wrap: anywhere;
}
.ticker-summary strong { font-size: 1rem; }
.ticker-summary small { display: block; color: #526177; }
.ticker-summary dl {
    display: grid; grid-template-columns: minmax(0, 1fr) auto;
    gap: .25rem .5rem; margin: .5rem 0 0;
}
.ticker-summary dd { margin: 0; text-align: right; font-weight: 600; }
.ticker-summary[data-selected="true"] { box-shadow: inset 0 0 0 2px #2860bd; }
</style>
"""


def trend_style(trend):
    color, background = TREND_COLORS.get(trend, ("#20283c", "#f2f4f8"))
    return f"color: {color}; background-color: {background}; font-weight: bold"


def select_ticker():
    click = st.session_state.get("ticker_click")
    if click:
        st.session_state.selected_ticker = click["label"]


def show_card(row, news, selected):
    ticker = row["Ticker"]
    name = row["Název"]
    currency = row["Měna"]
    name = name if pd.notna(name) and name else "Název není dostupný"
    date = row["Datum dat"]
    subtitle = f"{name} · {date}" if pd.notna(date) else name
    trend = row["Trend"]
    color, background = TREND_COLORS.get(trend, ("#20283c", "#f2f4f8"))
    ratio = "—" if pd.isna(row["R:R"]) else f"{row['R:R']:.2f} : 1"
    values = [
        ("Poslední cena", price_label(row["Cena"], currency)),
        ("ATR (14)", price_label(row["ATR14"], currency)),
        ("Trend", trend),
        ("Možný vstup", price_label(row["Vstup"], currency)),
        ("Stop-loss", price_label(row["Stop-loss"], currency)),
        ("Technický cíl", price_label(row["Cíl"], currency)),
        ("R:R", ratio),
    ]
    metrics = "".join(
        f"<dt>{label}</dt><dd style='color:{color if label == 'Trend' else '#20283c'}'>"
        f"{escape(value)}</dd>"
        for label, value in values
    )
    with st.container(border=True):
        st.html(
            f'<section class="ticker-summary" data-selected="{str(selected).lower()}" '
            f'style="background:{background}"><strong>{escape(ticker)}</strong>'
            f"<small>{escape(subtitle)}</small><dl>{metrics}</dl></section>"
        )
        condition = row.get("Podmínka vstupu")
        details = st.container() if selected else st.expander(f"Podrobnosti · {ticker}")
        with details:
            st.text(condition if pd.notna(condition) else row["Důvody"], wrap=True)
            shares = row["Akcie dle rizika a hotovosti"]
            if pd.notna(shares):
                value = price_label(row["Hodnota pozice (USD)"], "USD")
                loss = price_label(row["Modelová ztráta při stopu (USD)"], "USD")
                st.caption(f"Modelová pozice · {int(shares)} akcií · {value}")
                st.caption(f"Modelová ztráta při stopu · {loss}")

        with st.expander(f"Zprávy pro {ticker} · Yahoo Finance"):
            if news is None:
                st.info("Zprávy se nepodařilo načíst. Zkus analýzu spustit znovu.")
            elif not news:
                st.info("Yahoo Finance pro tento ticker neposkytlo žádné zprávy.")
            for title, publisher, published, url in news or []:
                st.text(title, wrap=True)
                date = published.strftime("%d.%m.%Y %H:%M UTC") if pd.notna(published) else "Datum neuvedeno"
                st.text(f"{date} · {publisher or 'Vydavatel neuveden'}")
                if url:
                    st.link_button("Otevřít článek", url, key=f"news-{ticker}-{url}")
                else:
                    st.caption("Odkaz není dostupný")


if refresh:
    st.session_state.pop("selected_ticker", None)
    tickers = list(dict.fromkeys(
        ticker.strip().upper()
        for ticker in tickers_text.replace("\n", ",").split(",")
        if ticker.strip()
    ))
    rows, news = [], {}
    if tickers:
        progress = st.progress(0)
        status_text = st.empty()
        for i, ticker in enumerate(tickers):
            status_text.text(f"Načítám ceny a zprávy pro {ticker}…")
            rows.append(analyze(ticker, period))
            try:
                news[ticker] = load_news(ticker)
            except Exception:
                news[ticker] = None
            progress.progress((i + 1) / len(tickers))
        status_text.empty()
        progress.empty()
    st.session_state.scan = {
        "rows": rows, "news": news,
        "updated": datetime.now(timezone.utc).astimezone().strftime("%d.%m.%Y %H:%M %Z"),
    }

scan = st.session_state.get("scan")
if scan is None:
    st.write("Zadej nebo ponech seznam tickerů vlevo a stiskni **Načíst data a analyzovat**.")
elif not scan["rows"]:
    st.warning("Zadej alespoň jeden ticker.")
else:
    st.subheader("Přehled tickerů")
    st.caption(
        f"Analýza spuštěna {scan['updated']}. "
        "Při opakovaném načtení může aplikace použít ceny uložené až 5 minut a zprávy až 15 minut."
    )
    rows = [size_position(row, capital, position_limit_usd) for row in scan["rows"]]
    df = pd.DataFrame(rows).sort_values(["Skóre", "Ticker"], ascending=[False, True])
    st.caption("Kliknutím na ticker v tabulce otevřeš jeho kartu hned pod přehledem.")
    st.caption(
        "Počet akcií se počítá u titulů v USD z poslední ceny, stopu vzdáleného 2× ATR, "
        "nejnižšího ze tří rizikových limitů a dostupného kapitálu."
    )
    st.dataframe(
        df.style.map(trend_style, subset=["Trend"]),
        hide_index=True, alt="Technické údaje a modelová velikost pozice pro jednotlivé tickery",
        column_order=[
            "Ticker", "Cena", "Měna", "Trend", "R:R", "Datum dat",
            *[column for column in df if column not in {"Ticker", "Cena", "Měna", "Trend", "R:R", "Datum dat"}],
        ],
        column_config={
            "Ticker": st.column_config.ButtonColumn("Ticker", key="ticker_click", on_click=select_ticker),
            "RSI": st.column_config.NumberColumn(format="%.1f"),
            "R:R": st.column_config.NumberColumn(format="%.2f"),
            "Skóre": st.column_config.NumberColumn(format="%d / 7"),
        },
    )
    st.download_button(
        "Stáhnout výsledky CSV", df.to_csv(index=False).encode("utf-8-sig"),
        file_name="trading_scan.csv", mime="text/csv",
    )

    st.subheader("Karty tickerů")
    st.html(CARD_STYLES)
    selected = st.session_state.get("selected_ticker")
    card_rows = sorted(df.to_dict("records"), key=lambda row: row["Ticker"] != selected)
    with st.grid(3, min_column_width=230):
        for row in card_rows:
            ticker = row["Ticker"]
            show_card(row, scan["news"][ticker], selected=ticker == selected)
