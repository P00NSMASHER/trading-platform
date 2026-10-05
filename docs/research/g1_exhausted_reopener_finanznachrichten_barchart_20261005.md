# G1 Exhausted Reopener Receipt — FinanzNachrichten + Barchart

Base main: `8014585b043217da5d5774382eb79e6a8b0972cc`
Canonical state at research start: 123/174 exact, 51 unresolved, token UNASSIGNED.

## New source-family basis

Two previously underused public syndication families were tested because they demonstrably preserve Business Wire publication clocks:

- FinanzNachrichten historical Business Wire pages display an explicit timestamp in `dd.mm.yyyy HH:MM Uhr` form.
- Barchart Business Wire stories display an explicit timestamp/timezone such as `Thu Feb 12, 7:00AM CST`.

These families are potentially admissible only when the exact target release page is recovered. Search-engine normalized publication fields, crawler time, import/update time, schedules, calls, EDGAR acceptance, date-only pages, neighboring releases, and inference remain rejected.

## Bounded exact-title/date pass

The following classifier-confirmed Business Wire unresolved events were searched by exact release title and target date in both families:

| Event | Symbol | Exact target release title | Owner |
|---|---|---|---|
| HEJFE-B9C8B3D0EF3DCB5E | CACI | CACI Reports Results for Its Fiscal 2015 Third Quarter | W1 |
| HEJFE-7CEFB3FE3D986464 | ROG | Rogers Corporation Reports 2014 Fourth Quarter and Year-End Results | W4 |
| HEJFE-947F50EBAFBA54DC | CRL | Charles River Laboratories Announces Fourth-Quarter and Full-Year 2014 Results from Continuing Operations and Provides 2015 Guidance | W4 |
| HEJFE-8A0517D50278EAE4 | POWI | Power Integrations Reports First-Quarter Financial Results | W1 |
| HEJFE-EBC49B9A024181AD | VEEV | Veeva Announces Fourth Quarter and Fiscal Year 2015 Results | W1 |
| HEJFE-45559DD90D876D39 | ILMN | Illumina Reports Strong Start to Fiscal Year 2015 | W0 |
| HEJFE-5D222F0F8E0C77D0 | TW | Towers Watson Reports Strong Third Quarter Earnings | W0 |
| HEJFE-FBA59D82CEE8FD00 | CGNX | Cognex Reports Record Results for 2014 | W2 |
| HEJFE-8EAA8616B1750B40 | CGNX | Cognex Reports Record First Quarter Revenue, Net Income and EPS | W4 |
| HEJFE-22BF36BABB9D19D7 | ALNY | Alnylam Pharmaceuticals Reports Fourth Quarter and Full Year 2014 Financial Results and Highlights Recent Period Progress | W4 |

Exact titles were independently reconfirmed from SEC or issuer copies.

## Result

No exact 2014/2015 target article with an explicit clock plus defensible timezone surfaced in either family through indexed public-web exact-title/date searches.

Observed false/non-target results included:
- later same-title POWI and ALNY Business Wire stories;
- unrelated Business Wire stories on FinanzNachrichten;
- date-only SEC/issuer copies.

Therefore FinanzNachrichten and Barchart are **EXHAUSTED_FOR_NOW for the ten events above** unless a direct historical article URL/ID, site index artifact, or alternate archived endpoint is recovered.

No G1 timestamp was promoted.

## Highest-leverage next artifact

A historical Business Wire article-ID/URL inventory, or another public mirror index that preserves Business Wire source IDs, would allow direct target-page lookup and could reopen this exact set efficiently.
