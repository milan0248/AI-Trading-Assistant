# AI Trading Assistant – v1.0

Český prototyp skeneru amerických akcií. Je určen pro analytiku a paper-trading workflow, nikoli pro automatické obchodování.

## Co umí
- Stáhne denní historická data vybraných tickerů přes `yfinance`.
- Spočítá EMA20/50/200, RSI14, ATR14, 20denní průlom a poměr objemu.
- Vytvoří transparentní skóre sledovaných podmínek.
- Vypočítá orientační velikost pozice podle zadaného rizika a 2×ATR stopu.
- Umožní export výsledků do CSV.
- Funguje v prohlížeči na počítači i mobilu, pokud je nasazen jako webová aplikace.

## Bezpečnostní omezení
- Žádné připojení k Trading 212.
- Žádné nákupní/prodejní příkazy.
- Žádná garance úplnosti, přesnosti nebo aktuálnosti dat.
- `yfinance` je neoficiální zdroj; data mohou být opožděná nebo nedostupná.
- Modelová velikost pozice nezohledňuje gap riziko, skluz, spread, poplatky, FX ani korelaci portfolia.
- Výsledek „SLEDOVAT“ není pokyn k nákupu.

## Spuštění na počítači

1. Nainstaluj Python 3.11 nebo novější: https://www.python.org/downloads/
2. Rozbal ZIP do složky.
3. Otevři terminál v této složce.
4. Spusť:

```bash
python -m venv .venv
```

Windows:
```bash
.venv\Scripts\activate
```

macOS:
```bash
source .venv/bin/activate
```

5. Nainstaluj knihovny:

```bash
pip install -r requirements.txt
```

6. Spusť aplikaci:

```bash
streamlit run app.py
```

Otevře se webová stránka v prohlížeči. Pro zastavení stiskni `Ctrl+C`.

## Mobil a přístup odkudkoli

Aplikace je webová. Pro bezpečný přístup z mobilu ji lze později nasadit na Streamlit Community Cloud nebo jiný hosting. Před veřejným nasazením je nutné doplnit přístupové zabezpečení. Nepřidávej do této první verze žádné broker API klíče.

## Další plán
1. Ověřit datový zdroj a časová razítka.
2. Doplnit backtesting se započtením spreadu, poplatků a skluzu.
3. Přidat paper-trading deník a kontrolu limitů ztrát.
4. Teprve poté přidat OpenAI API pro vysvětlování signálů a sumarizaci zpráv.
5. Trading 212 API připojit nejprve pouze pro čtení, s odděleným demo účtem a bez oprávnění k zadávání pokynů.
