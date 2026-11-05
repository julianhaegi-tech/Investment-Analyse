# Saxo Portfolio Analyse

Lokale Desktop-App zur nachträglichen Analyse eines Saxo-Depots. Sie läuft als einzelne `.exe`,
öffnet sich im Browser, speichert alles in einer lokalen SQLite-Datenbank und lädt Marktdaten
per Klick auf **Aktualisieren** aus kostenlosen Quellen.

## Funktionen

- **Import**
  - Saxo **Portfolio-Bericht (PDF)**: Bestand, Ø-Kaufkurs, Kontowert pro Stichtag,
    Quartalsrenditen vs. Saxo-Benchmark, G/V je ETF (auch bereits verkaufte), Kostenübersicht
  - Saxo **Trade-Export (Excel/CSV)**: jeder Kauf und Verkauf mit Datum, Stückzahl, Kurs und Gebühren.
    Deutsche und englische Spaltennamen werden automatisch erkannt.
  - Manuelle Erfassung bzw. Korrektur von Transaktionen in der App
- **Aktualisieren** (z. B. einmal im Monat)
  - Tageskurse aller ETFs (Yahoo Finance, Fallback: justETF)
  - Wechselkurse nach CHF (Yahoo, Fallback: EZB via Frankfurter)
  - Benchmarks, frei wählbar, z. B. SMI und MSCI ACWI, umgerechnet in CHF
  - Sektoren, Länder, Top-10-Positionen und Eckdaten (TER, Replikation …) der ETFs (justETF, Fallback: Yahoo)
- **Auswertungen**
  - Depotwert vs. eingezahltes Kapital, Wert je ETF über die Zeit (ETF-Wechsel sichtbar)
  - Geldgewichtete Rendite (IRR) und zeitgewichtete Rendite (TWR)
  - Vergleich mit Benchmarks, inklusive «gleiche Einzahlungen im Benchmark»
  - Zerlegung des Gewinns: realisiert, Kursgewinn, Währungseffekt
  - Monatsrenditen, Drawdown, Volatilität, Sharpe-Ratio
  - Sektoren, Länder und Top-Positionen mit deinem CHF-Anteil
  - Saxo-Kostenanalyse und Quartalsvergleich
  - Automatisch erzeugte Analyse in Textform

## Installation (Windows)

1. Auf GitHub unter **Actions → «Tests & Build» → neuester Lauf** das Artefakt
   **SaxoAnalyse-Windows** herunterladen und entpacken. Für einen festen Download-Link einen Tag
   `v1.0.0` pushen: Dann erscheint die `.exe` unter **Releases**.
2. `SaxoAnalyse.exe` doppelklicken. Windows SmartScreen kann warnen, weil die Datei nicht signiert ist:
   «Weitere Informationen → Trotzdem ausführen».
3. Die App öffnet sich im Browser (`http://127.0.0.1:8765`). Zum Beenden das Konsolenfenster schliessen
   oder in der App auf **Beenden** klicken.

Alternative ohne `.exe`: Python 3.10+ installieren und `start_windows.bat` (bzw. `start_mac_linux.sh`) ausführen.

## Daten aus Saxo exportieren

| Was | Wo in SaxoTraderGO | Wofür |
|---|---|---|
| Portfolio-Bericht (PDF) | Konto → Berichte → Portfolio-Bericht, Zeitraum ab Kontoeröffnung | Kosten, Quartale, Bestand, frühere ETFs |
| Trades (Excel) | Konto → Historie → Trades (bzw. Transaktionen), Zeitraum ab Kontoeröffnung → Export | exakte Kauf-/Verkaufsdaten |

Ohne Trade-Export legt die App aus dem PDF einen **geschätzten** Kauf an (Ø-Kurs, Datum geschätzt).
Er ist gelb markiert und wird beim Import des Trade-Exports automatisch ersetzt.

## Wie gerechnet wird

- **Umschichtungen:** Verkaufserlöse bleiben als Cash im Konto und bezahlen den nächsten Kauf.
  Nur der ungedeckte Teil eines Kaufs zählt als neue Einzahlung. Ein ETF-Wechsel erzeugt also
  keinen Einbruch und keine doppelte Einzahlung.
- **IRR (geldgewichtet):** deine persönliche Rendite p.a. Sie berücksichtigt, wann wie viel Geld investiert war.
- **TWR (zeitgewichtet):** die Rendite der Anlage selbst, bereinigt um Einzahlungen. So rechnet auch Saxo.
- **Währungseffekt:** `Stück × aktueller Kurs × (FX heute − Ø-FX beim Kauf)`. Der Ø-FX wird aus dem
  CHF-Einstandswert berechnet (inkl. Gebühren).
- **Benchmarks:** werden in CHF umgerechnet. Der «Was-wäre-wenn»-Vergleich investiert dieselben
  Beträge an denselben Tagen in den Benchmark.

## Datenschutz

Alle Daten liegen lokal in `%APPDATA%\SaxoAnalyse\portfolio.db` (macOS: `~/Library/Application Support/SaxoAnalyse`).
Nach aussen gehen nur Kursabfragen mit ISIN bzw. Ticker. Name, Adresse und Kontonummer aus dem
PDF werden nicht gespeichert. `*.pdf`, `*.xlsx` und `*.db` sind per `.gitignore` vom Repository ausgeschlossen.

## Grenzen der Gratis-Quellen

Yahoo Finance und justETF sind inoffizielle, kostenlose Schnittstellen und können sich ändern.
Darum hat jede Datenart einen Fallback. Was beim letzten Refresh geklappt hat, steht unter
**Einstellungen → Letzter Refresh**. Lädt ein ETF falsche Kurse, unter **Einstellungen → Ticker-Zuordnung**
den richtigen Yahoo-Ticker eintragen (z. B. eine Xetra-Notierung `….DE`).

## Entwicklung

```bash
pip install -r requirements.txt pytest
python -m pytest -q        # Tests (ohne Netzwerk, mit Mock-Marktdaten)
python run.py              # App starten
pyinstaller SaxoAnalyse.spec --noconfirm   # .exe bauen (unter Windows)
```

Struktur: `saxo_analyse/importers` (PDF/Excel), `market.py` (Datenquellen), `refresh.py` (Aktualisieren-Button),
`analytics.py` (Berechnungen), `insights.py` (Analyse-Text), `app.py` (lokaler Server), `static/` (Oberfläche).

*Keine Anlageberatung.*
