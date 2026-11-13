"""Gate di contratto sugli artifact — un unico posto, testabile.

Prima questi controlli erano **5 blocchi `python - <<'PY'` dentro i workflow**
(uno duplicato in `derive-smoke` e `pipeline`): non testabili con pytest, non
riusabili e mai eseguiti sul dato pubblicato. Qui diventano funzioni pure +
una CLI, così lo stesso gate può girare su fixture (PR), sull'output del build
e — quando serve — sul pubblicato.

Non cambia la semantica dei gate: è un'estrazione 1:1 dal YAML.

Comandi:

    python -m lab_tools.asserts urn-subset
    python -m lab_tools.asserts contract
    python -m lab_tools.asserts regex-resolution --max-bersagli 50

Exit code 0 = gate superato (anche quando la baseline non è raggiungibile:
comportamento storico, vedi `Limiti noti`), 1 = gate fallito.

**Limiti noti** (debito, non sviste):

- la baseline assente (404 al primo build, rete giù) **disattiva** il gate con
  un warning. Un gate che si spegne da solo è debole: quando il layer avrà una
  baseline stabile conviene renderlo bloccante (`--require-baseline`).
- questi assert guardano la *perdita* (URN/colonne/vigenze), non la *forma*
  (duplicati, coerenza cross-artifact, plausibilità): vedi `docs/PIPELINE.md`.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

# Baseline = raw dell'ultimo build, dal layer pubblico. `data/derived` non è
# in git: il gate confronta raw vs raw (stessa scelta di `pipeline.yml`).
RAW_BASELINE_URL = (
    "https://storage.googleapis.com/dataciviclab-clean/italia-corpus/_raw/2026/normativa.parquet"
)
BASELINE_LOCALE = Path("/tmp/main_normativa.parquet")

# Soglia minima di byte per considerare valida una baseline scaricata: un file
# troncato a metà non deve far passare o fallire per caso.
BASELINE_MIN_BYTES = 1000

ALLOWLIST_URN = Path("config/allowlist_urn_mancanti.txt")

# Bersagli distinti regex non risolti ammessi: un churn di filename (fetch che
# rinomina gli snapshot) fa crollare la risoluzione dei link. 2026-10-29:
# 11 -> 44.079 link non risolti, passato silenzioso per un intero build.
MAX_REGEX_BERSAGLI_NON_RISOLTI = 50

# Soglia del downgrade di vigenza: un atto corrente che torna ORIGINALE è una
# regressione (`legal_text` servirebbe l'originale). Oggi ~13,2k correnti.
VIGENZA_SOGLIA_PCT = 0.01
VIGENZA_SOGLIA_MIN = 50


# ---------------------------------------------------------------------------
# Funzioni pure (testabili senza I/O)
# ---------------------------------------------------------------------------


def diff_urn(main_urns: set[str], build_urns: set[str], ammessi: set[str]) -> list[str]:
    """URN presenti nella baseline e assenti dal build, esclusi gli ammessi.

    Invariante di identità: nessun atto può sparire build-over-build. Il
    2026-10-29 il Codice civile è stato cancellato da uno swap dopo un
    `syntax error` e il calo non ha fermato niente; la soglia sui link non
    basta (un atto poco citato non la supera), quindi si confrontano gli
    insiemi di URN.
    """
    return sorted(u for u in (set(main_urns) - set(build_urns)) if u not in ammessi)


def missing_columns(main_cols: list[str] | set[str], build_cols: list[str] | set[str]) -> list[str]:
    """Colonne della baseline assenti nel build (contratto backward-compatible)."""
    return sorted(set(main_cols) - set(build_cols))


def vigenza_downgrade(
    main_vig: int,
    build_vig: int,
    *,
    pct: float = VIGENZA_SOGLIA_PCT,
    minimo: int = VIGENZA_SOGLIA_MIN,
) -> int:
    """Atti correnti VIGENZA declassati **oltre** la soglia tollerata (0 = ok)."""
    soglia = max(minimo, int(main_vig * pct))
    return max(0, int(main_vig) - int(build_vig) - soglia)


def regex_unresolved(df: Any) -> tuple[int, int]:
    """(link non risolti, bersagli distinti non risolti) per gli archi regex.

    Si conta per **bersaglio** e non per link: così il gate è robusto a quanti
    link puntano allo stesso atto mancante.
    """
    regex = df[df["origine"] == "regex"]
    non_risolti = regex[~regex["risolto"]]
    return int(len(non_risolti)), int(non_risolti["bersaglio_filename"].nunique())


def renamed_files(main_files: set[str], build_files: set[str]) -> list[str]:
    """Nomi file spariti dalla baseline (rename/cancellazioni): **advisory**.

    Un rename puro non cambia l'insieme degli URN, quindi il gate di identità
    non lo vede: è la classe di incidente del 29/10 (stesso atto, nome nuovo →
    link rotti). Oggi resta un contatore visibile.
    """
    return sorted(set(main_files) - set(build_files))


def allowlist_urns(path: Path = ALLOWLIST_URN) -> set[str]:
    """URN ammessi a sparire, una per riga (`#` = commento)."""
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        urn = line.split("#", 1)[0].strip()
        if urn:
            out.add(urn)
    return out


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def scarica_baseline(url: str = RAW_BASELINE_URL, dest: Path = BASELINE_LOCALE) -> bool:
    """Scarica la baseline e la valida per dimensione. False = non disponibile.

    Stampa l'annotazione GitHub (::warning::) come faceva il blocco YAML.
    """
    try:
        urllib.request.urlretrieve(url, dest)
    except urllib.error.HTTPError as exc:
        # 404 = prima build che popola il layer (bootstrap).
        print(f"::warning::gate disattivato: baseline assente sul layer (HTTP {exc.code})")
        return False
    except Exception as exc:  # rete/timeout: il gate non deve rompere il build
        print(f"::warning::gate disattivato: errore di rete ({exc})")
        return False
    if not dest.exists() or dest.stat().st_size < BASELINE_MIN_BYTES:
        print("skip gate (snapshot non disponibile)")
        return False
    return True


def _colonna(path: Path, nome: str) -> list[str]:
    import pyarrow.parquet as pq

    return pq.read_table(path, columns=[nome])[nome].to_pylist()


def urns_di(path: Path) -> set[str]:
    return {u for u in _colonna(path, "urn") if u}


def files_di(path: Path) -> set[str]:
    return {f for f in _colonna(path, "filename") if f}


def vigenza_correnti(path: Path) -> int:
    """Atti correnti che sono espressione VIGENZA (non ORIGINALE)."""
    import pyarrow.parquet as pq

    t = pq.read_table(path, columns=["is_current", "versione"])
    cur = t.column("is_current").to_pylist()
    ver = t.column("versione").to_pylist()
    return sum(1 for c, v in zip(cur, ver) if c and (v or "") == "VIGENZA")


# ---------------------------------------------------------------------------
# Comandi
# ---------------------------------------------------------------------------


def cmd_urn_subset(args) -> int:
    baseline = Path(args.baseline)
    if not baseline.exists() and not scarica_baseline(args.baseline_url, baseline):
        return 0
    main_urns = urns_di(baseline)
    build_urns = urns_di(Path(args.build))
    mancanti = diff_urn(main_urns, build_urns, allowlist_urns(Path(args.allowlist)))
    print(
        f"gate urn: main={len(main_urns)} build={len(build_urns)} "
        f"mancanti={len(main_urns - build_urns)} non_ammessi={len(mancanti)}"
    )
    if mancanti:
        print(f"URN MANCANTI: {len(mancanti)} non in allowlist (es. {mancanti[:5]})")
        return 1
    return 0


def cmd_contract(args) -> int:
    baseline = Path(args.baseline)
    if not baseline.exists() and not scarica_baseline(args.baseline_url, baseline):
        return 0
    build = Path(args.build)

    missing = missing_columns(_schema_names(baseline), _schema_names(build))
    if missing:
        print(f"COLONNE MAIN MANCANTI: {missing}")
        return 1
    print(f"contract colonne ok: main={len(_schema_names(baseline))} build={len(_schema_names(build))}")

    main_vig = vigenza_correnti(baseline)
    build_vig = vigenza_correnti(build)
    print(
        f"contract vigenze: main={main_vig} build={build_vig} "
        f"soglia={max(VIGENZA_SOGLIA_MIN, int(main_vig * VIGENZA_SOGLIA_PCT))}"
    )
    if vigenza_downgrade(main_vig, build_vig):
        print(
            f"DOWNGRADE: {main_vig - build_vig} atti correnti non sono piu' "
            f"VIGENZA (main={main_vig}, build={build_vig})"
        )
        return 1

    spariti = renamed_files(files_di(baseline), files_di(build))
    if spariti:
        print(
            f"::warning::contract path: {len(spariti)} nomi file spariti "
            f"(rename/cancellazioni) — advisory (es. {spariti[:3]})"
        )
    else:
        print("contract path: 0 nomi file spariti")
    return 0


def _schema_names(path: Path) -> list[str]:
    import pyarrow.parquet as pq

    return list(pq.read_schema(path).names)


def cmd_regex_resolution(args) -> int:
    import pandas as pd

    df = pd.read_parquet(args.path)
    link, bersagli = regex_unresolved(df)
    print(f"riferimenti: {len(df)} archi · regex non risolti: {link} link / {bersagli} bersagli")
    if bersagli > args.max_bersagli:
        print(f"CHURN: {bersagli} bersagli regex non risolti ({link} link, max {args.max_bersagli})")
        return 1
    return 0


def cmd_schema(args) -> int:
    """Verifica che le colonne citate da `clean.sql` esistano nel raw reale.

    Nasce da un incidente concreto: aggiungere `esito` alla clean.sql e
    mergiare prima che il raw sul layer avesse la colonna → publish rosso con
    un Binder Error a metà run. `toolkit run --dry-run` **non** lo prende: il
    suo `raw_input` è un placeholder costruito dalle colonne dichiarate o
    quotate, non dallo schema vero (vedi `docs/PIPELINE.md`).

    Qui il legame avviene contro il **parquet vero** con `LIMIT 0`: nessun dato
    letto, ma DuckDB deve risolvere ogni colonna. Esito: 0 = ok/skip, 1 = fail.
    """
    campioni = [args.config] if args.config else sorted(str(p) for p in Path("datasets").glob("*/dataset.yml"))
    falliti = 0
    for cfg_path in campioni:
        esito = _schema_di_config(Path(cfg_path))
        if esito == "fail":
            falliti += 1
    return 1 if falliti else 0


def _schema_di_config(cfg_path: Path) -> str:
    """'ok' | 'skip' | 'fail' per un singolo dataset."""
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        print(f"::warning::schema {cfg_path}: config illeggibile ({exc})")
        return "skip"

    nome = str((cfg.get("dataset") or {}).get("name") or cfg_path.parent.name)
    raw_paths = _raw_locali(cfg, cfg_path.parent)
    if not raw_paths:
        # Il raw non è sul disco (dataset saltato dal Makefile, o layer non
        # scaricato): la clean.sql non può essere verificata qui.
        print(f"· schema {nome}: raw assente, skip")
        return "skip"
    if any(p.suffix.lower() != ".parquet" for p in raw_paths):
        # Il bind è su `read_parquet`: un raw CSV/XML non è verificabile qui.
        # Meglio saltare che bloccare la pipeline per un formato diverso.
        print(f"· schema {nome}: raw non parquet, skip")
        return "skip"

    sql_rel = (cfg.get("clean") or {}).get("sql")
    if not sql_rel:
        print(f"· schema {nome}: nessuna clean.sql")
        return "skip"
    sql_path = cfg_path.parent / sql_rel
    if not sql_path.exists():
        print(f"::warning::schema {nome}: {sql_path} non esiste")
        return "skip"

    try:
        import duckdb
    except ImportError:
        print(f"· schema {cfg_path.parent.name}: duckdb non disponibile, skip")
        return "skip"

    con = duckdb.connect()
    # Le macro standard servono solo se la SQL le usa: non facciamo skip
    # preventivo (in un ambiente senza toolkit il gate deve comunque valere
    # per le SQL che non usano macro).
    macro_ok = _carica_macro_toolkit(con)

    elenco = ", ".join(f"'{_sql_path(p)}'" for p in raw_paths)
    con.execute(f"CREATE VIEW raw_input AS SELECT * FROM read_parquet([{elenco}]) LIMIT 0")
    sql = _render(sql_path.read_text(encoding="utf-8"), cfg, cfg_path)
    try:
        con.execute(f"CREATE TABLE _schema_check AS {sql}")
    except Exception as exc:  # BinderException e affini
        if not macro_ok and _errore_macro(str(exc)):
            print(f"· schema {nome}: macro toolkit assenti, skip")
            return "skip"
        colonna = _colonna_secondo_duckdb(str(exc))
        dettaglio = f": colonna «{colonna}»" if colonna else ""
        print(f"SCHEMA NON COMPATIBILE {nome}{dettaglio}")
        print(f"  raw: {[p.name for p in raw_paths]}")
        print(f"  errore: {str(exc).splitlines()[0]}")
        return "fail"
    print(f"✓ schema {nome}: clean.sql compatibile col raw ({len(raw_paths)} file)")
    return "ok"


def _raw_locali(cfg: dict, base: Path) -> list[Path]:
    """Path esistenti delle sorgenti raw locali (relativi al dataset)."""
    out: list[Path] = []
    for src in (cfg.get("raw") or {}).get("sources") or []:
        if (src.get("type") or "") != "local_file":
            continue
        args = src.get("args") or {}
        p = args.get("path")
        if not p:
            continue
        risolto = (base / str(p)).resolve()
        if risolto.is_file():
            out.append(risolto)
        elif risolto.is_dir():
            out.extend(sorted(risolto.glob(args.get("filename") or "*")))
    return out


def _carica_macro_toolkit(con) -> bool:
    """Macro standard (`normalize_string`, …) come le carica il toolkit."""
    try:
        import toolkit

        macros = Path(toolkit.__file__).parent / "sql" / "macros.sql"
    except ImportError:
        return False
    if not macros.exists():
        return False
    con.execute(macros.read_text(encoding="utf-8"))
    return True


def _render(sql: str, cfg: dict, cfg_path: Path) -> str:
    """Sostituisce i placeholder del toolkit (`{year}`, `{dataset}`)."""
    anni = (cfg.get("dataset") or {}).get("years") or [2026]
    anno = anni[-1] if anni else 2026
    nome = (cfg.get("dataset") or {}).get("name") or cfg_path.parent.name
    return sql.replace("{year}", str(anno)).replace("{dataset}", str(nome))


def _errore_macro(msg: str) -> bool:
    """Vero se il bind è fallito perché manca una macro (non per lo schema)."""
    return bool(re.search(r"(Scalar Function|function)\s+\S+\s+does not exist", msg, re.IGNORECASE))


def _colonna_secondo_duckdb(msg: str) -> str | None:
    m = re.search(r'column "([^"]+)" not found', msg, re.IGNORECASE)
    if m:
        return m.group(1)
    m = re.search(r'Referenced column "([^"]+)"', msg, re.IGNORECASE)
    return m.group(1) if m else None


def _sql_path(p: Path) -> str:
    return str(p).replace("'", "''")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="lab_tools.asserts", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    u = sub.add_parser("urn-subset", help="nessun URN può sparire dalla baseline")
    u.add_argument("--build", default="data/derived/normativa.parquet")
    u.add_argument("--baseline", default=str(BASELINE_LOCALE))
    u.add_argument("--baseline-url", default=RAW_BASELINE_URL)
    u.add_argument("--allowlist", default=str(ALLOWLIST_URN))
    u.set_defaults(func=cmd_urn_subset)

    c = sub.add_parser("contract", help="colonne + vigenze + rename (advisory)")
    c.add_argument("--build", default="data/derived/normativa.parquet")
    c.add_argument("--baseline", default=str(BASELINE_LOCALE))
    c.add_argument("--baseline-url", default=RAW_BASELINE_URL)
    c.set_defaults(func=cmd_contract)

    r = sub.add_parser("regex-resolution", help="churn dei link regex non risolti")
    r.add_argument("--path", default="data/derived/riferimenti.parquet")
    r.add_argument("--max-bersagli", type=int, default=MAX_REGEX_BERSAGLI_NON_RISOLTI)
    r.set_defaults(func=cmd_regex_resolution)

    s = sub.add_parser("schema", help="le colonne di clean.sql esistono nel raw reale")
    s.add_argument("--config", default=None, help="un dataset.yml (default: tutti)")
    s.set_defaults(func=cmd_schema)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
