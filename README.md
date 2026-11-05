# Saxo Portfolio

Lokale Analyse eines Saxo-Depots – als Streamlit-App, gestartet über eine kleine `SaxoPortfolio.exe`
(gleiches Prinzip wie «Finanzen»: `app\` + `Daten\` neben der .exe, kein Konsolenfenster).

## Installation (Windows)

1. `SaxoPortfolio.zip` entpacken und den Ordner **SaxoPortfolio** z. B. auf den Desktop legen.
2. `SaxoPortfolio.exe` doppelklicken. Beim ersten Start werden die Python-Pakete einmalig installiert (1–2 Min).
3. Im Browser links den **Transaktions- und Saldenbericht (PDF)** hineinziehen.

Voraussetzung: Python 3.11+ (python.org). Ports 8790–8799 (kollidiert nicht mit «Finanzen», 8765–8784).

## Einziger Import

SaxoTraderGO → Konto → Berichte → **Transaktions- und Saldenbericht** → Zeitraum ab Kontoeröffnung → PDF.
Daraus liest die App alle Käufe/Verkäufe (Menge, Kurs, Wechselkurs, Betrag, Kosten), Einzahlungen,
Bestand (inkl. ISIN) und realisierte Gewinne. Depotwert, Gewinn, realisierte G/V und Kosten stimmen
exakt mit Saxo überein – auch ohne Internet.

**Kurse aktualisieren** (optional) lädt kostenlos Tageskurse (Yahoo Finance, Fallback justETF),
Wechselkurse (EZB), Benchmarks (MSCI ACWI, SMI) sowie Sektoren, Länder und Top-10 (justETF).

## Entwicklung

```bash
pip install -r app/requirements.txt pytest ziglang
python -m pytest -q                 # Tests (anonymisierte Bericht-Tabellen als Fixture)
streamlit run app/app.py            # App direkt starten
python tools/build_package.py       # baut dist/SaxoPortfolio.zip inkl. Windows-.exe (Cross-Compile mit Zig)
```

Struktur: `app/portfolio/report.py` (PDF-Import), `analytics.py` (Berechnungen), `market.py` (Gratis-Marktdaten),
`charts.py`, `insights.py`, `store.py` (SQLite in `Daten\`), `app/app.py` (Oberfläche), `app/launcher.pyw` +
`tools/launcher.c` (Starter).

*Keine Anlageberatung.*
