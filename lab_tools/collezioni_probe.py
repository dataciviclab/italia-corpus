"""Probe dei formati delle collezioni predefinite Normattiva.

Le collezioni sono bundle editoriali rigenerati dal portale: ogni giorno
possono cambiare formato disponibile (O = originale, V = vigente, M =
multivigente), numero di atti e `dataCreazione`. Il 2026-10-30 l'API ha
smesso di esporre **V** su 5 collezioni (Codici, Decreti Legislativi, Leggi
delega, Testi Unici, Leggi finanziarie): il pin in `config/collezioni.txt` le
congela, ma senza questo probe non sapremmo dire *da quanto*.

Questo stage fa **una** richiesta (`GET /collections/collection-predefinite`),
confronta la risposta con il pin e con il probe precedente e scrive
`data/derived/collezioni_probe.json` (committato: è la storia dei formati).

Stati per collezione:

- `ok` — il formato pinnato è disponibile
- `congelata` — il formato pinnato non è disponibile (il fetch salta, con
  warning: `fetch_normattiva._filtra_per_formato`)
- `non_pinnata` — in config senza pin: il fetch sceglie V > O > M
- `fuori_config` — esiste in Normattiva ma non la scarichiamo

Uso:
    python -m lab_tools.collezioni_probe
    python -m lab_tools.collezioni_probe --fail-on-missing   # gate CI
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime

from lab_tools._paths import OUTDIR, load_collezioni, load_pin
from lab_tools.normattiva_client import fetch_predefined_collections

logger = logging.getLogger(__name__)

PROBE_JSON = OUTDIR / "collezioni_probe.json"

STATO_OK = "ok"
STATO_CONGELATA = "congelata"
STATO_NON_PINNATA = "non_pinnata"
STATO_FUORI_CONFIG = "fuori_config"


def raggruppa(righe: list[dict]) -> dict[str, dict]:
    """`nomeCollezione -> {formato: {numero_atti, data_creazione}}`.

    La risposta grezza ha una riga per (collezione, formato); il report vuole
    la collezione come unità, con tutti i formati disponibili.
    """
    out: dict[str, dict] = {}
    for r in righe:
        nome = (r.get("nomeCollezione") or "").strip()
        fmt = (r.get("formatoCollezione") or "").strip().upper()
        if not nome or not fmt:
            continue
        out.setdefault(nome, {})[fmt] = {
            "numero_atti": r.get("numeroAtti"),
            "data_creazione": r.get("dataCreazione"),
        }
    return out


def costruisci_report(
    raggruppate: dict[str, dict],
    pin: dict[str, str],
    config: list[str],
    precedente: dict | None = None,
) -> dict:
    """Report di stato + cambiamenti rispetto al probe precedente (pura).

    Args:
        raggruppate: output di `raggruppa` (collezione -> formati).
        pin: `config/collezioni.txt` (`nome -> formato richiesto`).
        config: nomi delle collezioni che scarichiamo.
        precedente: JSON del probe precedente (o None al primo giro).

    Returns:
        Dict serializzabile con `sintesi`, `collezioni` (una riga per
        collezione) e `cambiamenti` (testo, vuoto se nulla si è mosso).
    """
    precedenti: dict[str, dict] = {}
    if precedente:
        precedenti = {c["nome"]: c for c in precedente.get("collezioni", [])}

    in_config = set(config)
    righe: list[dict] = []
    cambiamenti: list[str] = []

    for nome in sorted(raggruppate):
        formati = raggruppate[nome]
        richiesto = pin.get(nome)
        if nome not in in_config:
            stato = STATO_FUORI_CONFIG
        elif richiesto is None:
            stato = STATO_NON_PINNATA
        elif richiesto in formati:
            stato = STATO_OK
        else:
            stato = STATO_CONGELATA

        prev = precedenti.get(nome, {})
        senza_pin_da = 0
        if stato == STATO_CONGELATA:
            senza_pin_da = int(prev.get("senza_pin_da") or 0) + 1

        # cambiamenti: formati comparsi/spariti e atti (solo se il probe
        # precedente esisteva — al primo giro non c'è nulla da confrontare)
        if prev:
            vecchi = set(prev.get("formati") or [])
            nuovi = set(formati)
            for fmt in sorted(nuovi - vecchi):
                cambiamenti.append(f"{nome}: formato {fmt} comparso")
            for fmt in sorted(vecchi - nuovi):
                cambiamenti.append(f"{nome}: formato {fmt} sparito")
            if prev.get("stato") == STATO_CONGELATA and stato == STATO_OK:
                cambiamenti.append(f"{nome}: sbloccata ({richiesto} di nuovo disponibile)")

        righe.append(
            {
                "nome": nome,
                "in_config": nome in in_config,
                "pin": richiesto,
                "formati": sorted(formati),
                "numero_atti": {f: v.get("numero_atti") for f, v in sorted(formati.items())},
                "data_creazione": {
                    f: v.get("data_creazione") for f, v in sorted(formati.items())
                },
                "stato": stato,
                "senza_pin_da": senza_pin_da,
            }
        )

    # collezioni in config che l'API non espone più (rimosse dalla fonte)
    for nome in sorted(in_config - set(raggruppate)):
        cambiamenti.append(f"{nome}: assente dalla risposta API")
        righe.append(
            {
                "nome": nome,
                "in_config": True,
                "pin": pin.get(nome),
                "formati": [],
                "numero_atti": {},
                "data_creazione": {},
                "stato": STATO_CONGELATA,
                "senza_pin_da": int((precedenti.get(nome) or {}).get("senza_pin_da") or 0) + 1,
            }
        )

    sintesi = {
        "collezioni_api": len(raggruppate),
        "in_config": len(in_config),
        "pin_ok": sum(1 for r in righe if r["stato"] == STATO_OK),
        "congelate": sum(1 for r in righe if r["stato"] == STATO_CONGELATA),
        "non_pinnate": sum(1 for r in righe if r["stato"] == STATO_NON_PINNATA),
        "fuori_config": sum(1 for r in righe if r["stato"] == STATO_FUORI_CONFIG),
    }
    return {"sintesi": sintesi, "collezioni": righe, "cambiamenti": cambiamenti}


def stampa(report: dict, precedente: dict | None) -> None:
    """Output umano: sintesi, congelate con da-quanti-probe, cambiamenti."""
    s = report["sintesi"]
    print(
        f"collezioni API: {s['collezioni_api']} · in config: {s['in_config']} · "
        f"pin ok: {s['pin_ok']} · congelate: {s['congelate']} · non pinnate: {s['non_pinnate']} · "
        f"fuori config: {s['fuori_config']}"
    )
    congelate = [c for c in report["collezioni"] if c["stato"] == STATO_CONGELATA]
    if congelate:
        print("\ncongelate (pin non disponibile — il fetch salta, file esistenti mantenuti):")
        for c in congelate:
            disponibili = ", ".join(c["formati"]) or "nessuno"
            print(
                f"  {c['nome'][:48]:48s} pin {c['pin'] or '-':2s} · API {disponibili:8s} "
                f"· da {c['senza_pin_da']} probe"
            )
        if not precedente:
            print("  (primo probe: il contatore parte da 1)")

    fuori = [c for c in report["collezioni"] if c["stato"] == STATO_FUORI_CONFIG]
    if fuori:
        print("\nfuori config (esistono in Normattiva, non le scarichiamo):")
        for c in fuori:
            # numeroAtti è per formato: lo stesso insieme di atti, non sommare
            atti = max(c["numero_atti"].values(), default=0)
            print(f"  {c['nome'][:48]:48s} formati {', '.join(c['formati'])} · atti {atti}")

    print("\ncambiamenti:")
    if report["cambiamenti"]:
        for c in report["cambiamenti"]:
            print(f"  · {c}")
    else:
        print("  nessuno" if precedente else "  (primo probe: nessun confronto)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe formati collezioni Normattiva")
    parser.add_argument(
        "--fail-on-missing",
        action="store_true",
        help="Exit 1 se una collezione pinnata ha perso il formato (gate CI).",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    precedente = None
    if PROBE_JSON.exists():
        try:
            precedente = json.loads(PROBE_JSON.read_text())
        except json.JSONDecodeError:
            logger.warning("probe precedente illeggibile: lo ignoro")

    righe = fetch_predefined_collections()
    report = costruisci_report(raggruppa(righe), load_pin(), load_collezioni(), precedente)
    report["probed_at"] = datetime.now().isoformat(timespec="seconds")

    stampa(report, precedente)

    PROBE_JSON.parent.mkdir(parents=True, exist_ok=True)
    PROBE_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(f"\nprobe: {PROBE_JSON}")

    if args.fail_on_missing and report["sintesi"]["congelate"]:
        logger.error("collezioni congelate: %d", report["sintesi"]["congelate"])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
