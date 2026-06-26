# Runbook: diagnòstic i alleujament (DUGi-Doc / DSpace)

Guia de referència per diagnosticar saturació al servidor de producció i alleujar
símptomes aguts abans d’atacar causes arrel. Pensada per l’apilament habitual:

**Apache + Anubis → Tomcat (DSpace) → Postgres + Solr**

També cobreix l’ús de les eines d’aquest repo (`watch`, `ruleset`, `consolidate`) i
nftables.

---

## Estratègia en dues fases

| Fase | Objectiu | Horitzó |
|------|----------|---------|
| **1. Alleujar** | Usuaris poden treballar; evitar OOM i swap thrashing | Hores |
| **2. Arrel** | Evitar recurrència (heap, Solr, Postgres, disc) | Dies/setmanes |

**No** seguir un ordre fix Apache → Tomcat → Postgres sense mesurar abans.
Primer separar **símptoma agut** (disc/swap) de **causa estructural** (bots, heap,
queries, indexació Solr).

### Ordre d’intervenció recomanat

1. **Mesurar** (baseline o incident) — 5–30 min
2. **Aturar swap thrashing** i protegir serveis Java
3. **Reduir entrada inútil** (nftables, Anubis, paths abusius)
4. **Alleugerir I/O de fons** (Solr stats, logs)
5. **Afinar per capa** amb dades: entrada → Tomcat/Solr → Postgres → disc/SO

### Ordre d’afinament per capa (un cop mesurat)

| Ordre | Capa | Per què |
|-------|------|---------|
| 1 | Entrada (nftables + Anubis/Apache) | Cada petició evitada no consumeix worker, thread Tomcat ni query |
| 2 | Tomcat + Solr | Acumulen la major part de la RAM; Solr indexant és molt I/O |
| 3 | Postgres | Sovint víctima de pressió de disc/RAM, no causa primària |
| 4 | Disc / SO | SSD, rotació logs, separar dades de Solr si cal |

---

## El cicle de feedback (per què “més peticions = tot es va a la merda”)

```
Més peticions (bots)
    → més workers Apache + threads Tomcat
    → més queries Postgres + escriptures Solr (estadístiques)
    → més RAM + més I/O de disc
    → swap
    → tot més lent
    → més connexions obertes esperant resposta
    → més peticions “penjades”
    → OOM Tomcat / caiguda
```

**Filtrar abans** trenca el bucle al principi. **Reduir Solr I/O** el trenca al mig.
**Heap/timeouts** eviten que exploti al final.

Bloquejar IPs o països és **alleujament temporal**, no cura. Serveix per guanyar
temps mentre s’investiga la causa real.

---

## Checklist de comandes

Desa la sortida de cada sessió:

```bash
mkdir -p ~/incident-$(date +%Y%m%d-%H%M)
cd ~/incident-$(date +%Y%m%d-%H%M)
script triage.log
```

### A. Triage ràpid (2–5 min)

```bash
date; uptime; free -h; swapon --show

# Swap actiu? (si/so > 0 de forma continuada = molt dolent)
vmstat 1 10

# Disc saturat?
iostat -xz 1 10

# Qui menja CPU/RAM
ps aux --sort=-%mem | head -20
ps aux --sort=-%cpu | head -20

# Connexions
ss -s
ss -tan state established | wc -l
ss -tan state syn-recv | wc -l
```

**RAM realment disponible** (millor que `free` sol):

```bash
free -h
grep -E 'MemTotal|MemAvailable|SwapTotal|SwapFree' /proc/meminfo
```

### B. Qui escriu al disc (5 min)

```bash
sudo iotop -oPa -d 2 -n 15
# Alternativa:
sudo pidstat -d 1 10

sudo du -sh /var/solr/* /var/log/apache2/* /var/lib/postgresql/* 2>/dev/null | sort -hr | head -20
df -hT
df -i
lsblk
```

### C. Tràfic entrant (5–10 min)

```bash
# Top IPs (Anubis)
sudo tail -n 50000 /var/log/apache2/anubis_access.log | \
  awk '{print $1}' | sort | uniq -c | sort -rn | head -30

# Top paths
sudo tail -n 50000 /var/log/apache2/anubis_access.log | \
  awk -F'"' '{print $2}' | awk '{print $2}' | sort | uniq -c | sort -rn | head -20

# Errors
sudo tail -n 5000 /var/log/apache2/anubis_error.log
sudo journalctl -u tomcat8 --since "10 min ago" --no-pager | tail -50
```

**Amb `watch` (des del repo, en viu):**

```bash
ssh user@servidor 'sudo tail -F /var/log/apache2/anubis_access.log /var/log/apache2/anubis_error.log' | \
  uv run python main.py watch --config watch.example.yaml
```

**Mostra offline:**

```bash
ssh user@servidor 'sudo tail -n 100000 /var/log/apache2/anubis_access.log' > /tmp/anubis_sample.log
uv run python main.py watch --no-live --config watch.example.yaml /tmp/anubis_sample.log
```

### D. Postgres i Tomcat

```bash
sudo -u postgres psql -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"

sudo -u postgres psql -c "
  SELECT pid, now()-query_start AS dur, state, left(query,80)
  FROM pg_stat_activity
  WHERE state != 'idle' AND now()-query_start > interval '30 seconds'
  ORDER BY dur DESC;"

ps aux | grep -E '[j]ava|[s]olr'
sudo tail -n 100 /var/log/tomcat8/catalina.out 2>/dev/null
```

### E. Alleujament immediat (reversible)

**E1. Filtrar abans d’Apache (màxim impacte en pic)**

- Preferir **subnets /24** o **paths** abusius abans que bloquejar un país sencer.
- Whitelist: Espanya (`ES`), xarxa UDG `84.88.0.0/16`, localhost (veure `watch.example.yaml`).
- Consolidar IPs sospitoses:

```bash
uv run python main.py consolidate suspicious_ips.txt \
  --geoip-db GeoLite2-Country_20260612/GeoLite2-Country.mmdb
```

- Analitzar ruleset nftables actual:

```bash
sudo nft list ruleset > nft_ruleset.nft
uv run python main.py ruleset nft_ruleset.nft \
  --geoip-db GeoLite2-Country_20260612/GeoLite2-Country.mmdb
```

**Accions al firewall que sí ajuden (petit cost, benefici clar):**

- Eliminar regles `drop` que apunten a **sets buits** (lookups sense efecte).
- Fusionar sets actius en un sol `drop` (menys lookups per connexió nova).

La consolidació CIDR en un ruleset amb IPs escampades sol donar poc (<5%).

**E2. Reduir I/O Solr** — pausar o desacoblar indexació d’estadístiques en hores punta.

**E3. Apache / Anubis** — `MaxRequestWorkers` i timeouts cap a Tomcat més curts alliberen
workers quan el backend va lent per swap.

```bash
sudo apache2ctl configtest
sudo systemctl reload apache2
```

**E4. Swap (supervivència, no cura)**

```bash
cat /proc/sys/vm/swappiness
sudo sysctl -w vm.swappiness=10
# Només en emergència extrema:
sync; echo 3 | sudo tee /proc/sys/vm/drop_caches
```

### F. Paquet post-incident

```bash
mkdir -p ~/incident-$(date +%Y%m%d) && cd ~/incident-$(date +%Y%m%d)
{
  date; uptime; free -h; swapon --show
  vmstat 1 30
  iostat -xz 1 30
  ps aux --sort=-%mem | head -30
  ss -s
  sudo iotop -b -o -d 2 -n 30
} | tee triage.log

sudo journalctl --since "YYYY-MM-DD HH:MM" --until "YYYY-MM-DD HH:MM" > journal.log
sudo nft list ruleset > nft_ruleset.nft
```

### G. Decisió: bloquejar país o subnet?

Abans de bloquejar US/CN sencer:

1. Executar `watch` sobre una mostra de log.
2. Si >50% del RPS és abús en paths de cerca/discover i quasi zero descàrregues reals →
   bloqueig temporal té sentit.
3. Si hi ha barreja amb usuaris reals (VPN, erasmus, crawlers) → millor **subnet + path**.

---

## Interpretar sortides

### `vmstat 1 10`

```
procs -----------memory---------- ---swap-- -----io---- -system-- ------cpu-----
 r  b   swpd   free   buff  cache   si   so    bi    bo   in   cs us sy id wa st
```

| Camp | Significat | Tranquil | Incident |
|------|------------|----------|----------|
| **r** | Processos esperant CPU | 0–2 | 4+ constant |
| **b** | Bloquejats per I/O | 0 | >0 sostingut |
| **swpd** | RAM al swap (KB) | 0 ideal | >0 indica pressió passada o actual |
| **free** | RAM “lliure” | Enganyós si **cache** és alt | — |
| **cache** | Page cache | Normal en Linux | — |
| **si / so** | Swap in/out per segon | **0** | >0 continu = thrashing |
| **wa** | % CPU esperant disc | <5% | 20–80% |
| **id** | % CPU ociosa | alt | baix |

**Nota:** `free` baix amb `cache` alt (ex. 11 GB) és normal. Mirar `MemAvailable`.

### `iostat -xz 1 10`

La primera taula = mitjana des del boot. Les següents = per segon (més útil en incident).

| Camp | Significat | Tranquil | Incident |
|------|------------|----------|----------|
| **%util** | % temps disc ocupat | <20% | >80% sostingut |
| **await** | ms mitjana per I/O | <20 | >100 |
| **w_await** | Latència escriptura | baix | alt (Solr, WAL, logs) |
| **avgqu-sz** | Cua d’operacions | <1 | >2–4 |

### `ss -s`

| Camp | Significat | Tranquil | Incident |
|------|------------|----------|----------|
| **estab** | Connexions actives | centenars | milers |
| **synrecv** | Half-open (SYN) | 0–pocs | centenars+ |
| **timewait** | Connexions tancades recentment | normal HTTP | — |

### `ps aux`

| Procés | Què mirar | Senyal d’alerta |
|--------|-----------|-----------------|
| **Tomcat (dspace)** | %CPU, %MEM, RSS vs `-Xmx` | RSS >> heap (fuga nativa, threads, pool) |
| **Postgres** | connexions `idle` vs `active`, RSS | moltes idle grans = pool massa gran |
| **Apache** | workers × RSS | tots al top de CPU en pic |
| **Solr** | CPU + I/O associat | indexació en hores punta |

**Exemple de línia base (moment tranquil):**

- `vmstat`: `si/so` ≈ 0, `wa` 0–2%, `id` ~100% → no hi ha saturació **ara**.
- `swpd` ~300 MB → la RAM ja ha estat justa en algun moment.
- Tomcat ~56% RAM, ~57% CPU amb `-Xmx3g` però RSS ~9 GB → investigar memòria fora del heap.
- Apache/Anubis ~1% CPU → la pressió en pic vindrà de darrere (Tomcat/Solr/disc).

---

## Rendiment del ruleset nftables

Cadena `input` típica:

```
iif lo accept
ct state established,related accept   ← la majoria de tràfic surt aquí
ip saddr @set1 drop
...
```

Només els **fluxos nous** (SYN, primers paquets) passen pels `drop`. El tràfic
`established` no fa lookups als sets.

| Acció | CPU | Memòria kernel | Memòria Tomcat/Postgres |
|-------|-----|---------------|-------------------------|
| Eliminar sets buits | Petit guany | — | — |
| Fusionar sets | Petit guain | Igual | — |
| Consolidació CIDR (IPs escampades) | ~res | ~res | — |

~64k IPs en sets ≈ **5–15 MB** de kernel — insignificant davant heap JVM.
El firewall **protegeix** memòria bloquejant abans d’Apache; no arregla OOM per si sol.

---

## Eines d’aquest repo

| Comanda | Ús |
|---------|-----|
| `main.py watch` | RPS en viu, països, bursts, recomanacions de bloc |
| `main.py ruleset` | Analitzar dump nftables: països, sets, consolidació |
| `main.py consolidate` | IPs → CIDRs per afegir a firewall |

Config de referència: `watch.example.yaml` (whitelist `ES`, `84.88.0.0/16`, `127.0.0.1`).

---

## Comandes d’aprofundiment (en calma)

```bash
# Memòria Tomcat fora del heap (PID d’exemple)
sudo -u dspace jcmd <PID> VM.native_memory summary 2>/dev/null

# On munta cada disc
df -hT

# Solr
ps aux | grep -i solr
sudo tail -f /var/solr/logs/solr.log
```

---

## Referències internes

- Ruleset d’exemple analitzat: `ruleset_20260625.json` (~64k IPs, sets `bots2` + `lnegreregles`)
- Informes generats: `reports/ruleset/` (JSON, CSV països, CIDRs, `.nft` simplificat)
- README: secció `watch` i enllaç a aquest document
