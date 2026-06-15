# estimate_download_costs

Eina per analitzar fitxers de log Apache de descàrregues de documents i calcular estadístiques agregades: interval de dates, nombre de registres i volum total de dades transferides.

## Requisits

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) (recomanat) o un altre gestor de dependències

## Instal·lació

```bash
git clone git@github.com:oooriii/estimate_download_costs.git
cd estimate_download_costs
uv sync
```

## Ús

Passa el fitxer de log com a argument:

```bash
uv run python main.py 20260615_downloads_ddocs.txt
```

Ajuda:

```bash
uv run python main.py --help
```

### Sortida

L'eina mostra un panell amb:

| Camp | Descripció |
|------|------------|
| **Fitxer** | Ruta del fitxer analitzat |
| **Data mínima** | Timestamp del registre més antic |
| **Data màxima** | Timestamp del registre més recent |
| **Registres** | Nombre total de línies vàlides parsejades |
| **Bytes descarregats** | Suma dels bytes transferits (format llegible: KB, MB, GB…) |

Mentre processa el fitxer es mostra una barra de progrés amb el nombre de registres llegits.

## Format de log esperat

Cada línia segueix el format *combined* d'Apache amb un prefix que indica el fitxer d'origen del log:

```
/var/log/apache2/access_ssl_anubis.log:- - - [15/Jun/2026:06:26:23 +0200] "GET /bitstream/handle/10256/23347/document.pdf?sequence=1 HTTP/1.1" 200 11555603 "-" "Mozilla/5.0 ..."
```

El parser extreu per cada línia:

- fitxer de log d'origen
- host remot (IP, IPv6 o `-`)
- data i hora
- mètode, ruta i protocol HTTP
- codi d'estat i bytes transferits
- referrer i user-agent

Les línies que no coincideixen amb aquest format s'ignoren.

## Ús com a llibreria

```python
from pathlib import Path
from main import parse_file

stats = parse_file(Path("20260615_downloads_ddocs.txt"))
print(stats.min_date, stats.max_date, stats.total_records, stats.total_bytes)
```

## Fitxers de dades

Els fitxers de log d'entrada (`20260615_downloads_*.txt`) estan exclosos del control de versions via `.gitignore` per la seva mida. Cal tenir-los localment per executar l'anàlisi.

## Llicència

Veure [LICENSE](LICENSE).
