"""ACQ-R14 step 2: license audit of every source dataset (directive section 5.1), read from landing-page metadata through
documented services, never by HTML scraping:

  * DOI-registered datasets (MGDS/IEDA, PANGAEA, USGS): DataCite REST API, `rightsList` of the DOI record.
  * NCEI multibeam cruises (no DOI): the cruise's ISO 19115 record served by NCEI; NOAA data are U.S. Government
    works (public domain); the record's constraints are liability / not-for-navigation disclaimers.
  * MGDS data sets without a DOI in the MGDS data-service harvest: DOI prefixes are probed on DataCite; if none
    resolves, the license is recorded as "not stated in a DOI record" (MGDS default terms, ACQ-R08 H-3) and marked
    `confirm`.

Writes reports_post_grl_review/ACQ-R14/license_audit.{json,csv}. Throttled (0.5 s between requests) and cached.

    python -B -m src.acq_r14.license_audit
"""
from __future__ import annotations
import csv, re, time, xml.etree.ElementTree as ET
from pathlib import Path
import requests
from . import common as C

CACHE = C.RPT / "license_cache"
RECORD_LICENSE = "CC BY-NC-SA 4.0"      # Steve's ruling 2026-10-20 (ACQ-R14 H-1 option b): the whole record
NCEI_ISO = "https://www.ngdc.noaa.gov/metadata/published/NOAA/NESDIS/NGDC/MGG/Multibeam/iso/xml/{cruise}_Multibeam.xml"
MGDS_PREFIXES = ("10.60521/3{uid}", "10.26022/IEDA/3{uid}", "10.1594/IEDA/3{uid}")
NS = {"gmd": "http://www.isotc211.org/2005/gmd", "gco": "http://www.isotc211.org/2005/gco"}


def _get(url: str, headers=None, timeout=60) -> requests.Response | None:
    time.sleep(0.5)
    try:
        r = requests.get(url, headers={**C.HEADERS, **(headers or {})}, timeout=timeout, allow_redirects=True)
    except requests.RequestException as e:
        C.log(f"  request failed {url}: {e}")
        return None
    return r


def datacite(doi: str) -> dict | None:
    key = CACHE / ("datacite_" + re.sub(r"[^A-Za-z0-9]+", "_", doi) + ".json")
    if key.exists():
        return C.jload(key)
    r = _get(f"https://api.datacite.org/dois/{doi}", headers={"Accept": "application/vnd.api+json"})
    if r is None or r.status_code != 200:
        out = {"doi": doi, "status": r.status_code if r is not None else None, "found": False}
    else:
        a = r.json()["data"]["attributes"]
        out = {"doi": doi, "found": True, "status": 200, "title": (a.get("titles") or [{}])[0].get("title"),
               "creators": [c.get("name") for c in a.get("creators") or []], "publisher": a.get("publisher"),
               "publicationYear": a.get("publicationYear"), "url": a.get("url"), "rightsList": a.get("rightsList") or [],
               "retrieved": C.utcnow(), "source": f"https://api.datacite.org/dois/{doi}"}
    C.jdump(out, key)
    return out


def ncei(cruise: str) -> dict:
    key = CACHE / f"ncei_{cruise}.json"
    if key.exists():
        return C.jload(key)
    url = NCEI_ISO.format(cruise=cruise)
    r = _get(url)
    out = {"cruise": cruise, "source": url, "retrieved": C.utcnow(), "found": False}
    if r is not None and r.status_code == 200 and (b"MI_Metadata" in r.content or b"MD_Metadata" in r.content):
        try:
            root = ET.fromstring(r.content)
            title = root.find(".//gmd:identificationInfo//gmd:citation//gmd:title/gco:CharacterString", NS)
            codes = [e.get("codeListValue") for e in root.iter("{http://www.isotc211.org/2005/gmd}MD_RestrictionCode")]
            texts = [e.text.strip() for e in root.iter("{http://www.isotc211.org/2005/gco}CharacterString")
                     if e.text and re.search(r"liabilit|navigation|public domain|restrict|constraint|warrant", e.text, re.I)]
            out.update(found=True, title=title.text if title is not None else None, restriction_codes=sorted(set(c for c in codes if c)),
                       constraint_texts=sorted(set(t[:300] for t in texts))[:8])
        except ET.ParseError as e:
            out["error"] = f"parse: {e}"
    else:
        out["status"] = r.status_code if r is not None else None
    C.jdump(out, key)
    return out


USGS_FGDC = {  # FGDC metadata linked from the CMGDS landing page (the documented download path, ruling 2026-06-02)
    "10.5066/P97QM7NF": "https://cmgds.marine.usgs.gov/data-releases/media/2021/10.5066-P97QM7NF/73ebf318e0cf4599a8fc28dacf25dd51/2021-603-DD_bathy_201804_metadata.xml"}


def usgs_fgdc(doi: str) -> dict | None:
    url = USGS_FGDC.get(doi)
    if not url:
        return None
    key = CACHE / ("usgs_" + re.sub(r"[^A-Za-z0-9]+", "_", doi) + ".json")
    if key.exists():
        return C.jload(key)
    r = _get(url)
    out = {"doi": doi, "source": url, "retrieved": C.utcnow(), "found": False}
    if r is not None and r.status_code == 200:
        m_use = re.search(r"<useconst>(.*?)</useconst>", r.text, re.S)
        m_acc = re.search(r"<accconst>(.*?)</accconst>", r.text, re.S)
        out.update(found=True, useconst=(m_use.group(1).strip() if m_use else None), accconst=(m_acc.group(1).strip() if m_acc else None))
    C.jdump(out, key)
    return out


def mgds_landing(uid: str) -> dict:
    """MGDS data set page (https://www.marine-geo.org/tools/files/<uid>): the embedded schema.org JSON-LD carries `license`."""
    key = CACHE / f"mgds_{uid}_landing.json"
    if key.exists():
        return C.jload(key)
    url = f"https://www.marine-geo.org/tools/files/{uid}"
    r = _get(url)
    out = {"uid": uid, "source": url, "retrieved": C.utcnow(), "license": None, "title": None}
    if r is not None and r.status_code == 200:
        (CACHE / f"mgds_{uid}_landing.html").write_bytes(r.content)
        m = re.search(r'"license"\s*:\s*"([^"]+)"', r.text)
        t = re.search(r'"name"\s*:\s*"([^"]+)"', r.text)
        out.update(license=m.group(1) if m else None, title=t.group(1) if t else None, status=200)
    else:
        out["status"] = r.status_code if r is not None else None
    C.jdump(out, key)
    return out


def classify(rights: list[dict]) -> tuple[str, str]:
    """-> (license label, redistribution: yes | yes_conditional | no | confirm)."""
    if not rights:
        return "not stated in the DOI record", "confirm"
    txt = " | ".join((r.get("rights") or "") + " " + (r.get("rightsUri") or "") for r in rights)
    low = txt.lower()
    if "cc0" in low or "publicdomain/zero" in low or "public domain" in low:
        return "CC0 1.0 / public domain", "yes"
    if "by-nc-sa" in low or ("noncommercial" in low and "share" in low):
        return re.sub(r"\s+", " ", rights[0].get("rights") or "CC BY-NC-SA"), "yes_conditional"
    if "by-nc" in low or "noncommercial" in low:
        return re.sub(r"\s+", " ", rights[0].get("rights") or "CC BY-NC"), "yes_conditional"
    if "by-sa" in low:
        return re.sub(r"\s+", " ", rights[0].get("rights") or "CC BY-SA"), "yes_conditional"
    if "licenses/by/" in low or "attribution 4.0" in low or "cc-by" in low or "cc by" in low:
        return re.sub(r"\s+", " ", rights[0].get("rights") or "CC BY"), "yes"
    if "restrict" in low or "no redistribution" in low or "all rights reserved" in low:
        return txt[:120], "no"
    return txt[:120], "confirm"


def ncei_cruise_from_entry(e: dict) -> str | None:
    """The NCEI survey id used for the ship side: manifest lr_cruise / cruise_id, else from the products' NCEI URLs."""
    m = e.get("manifest") or {}
    for k in ("lr_cruise", "cruise_id"):
        v = m.get(k)
        if v and isinstance(v, str) and v not in ("Cal DIG I",) and not v.startswith("SO") and not v.startswith("M1") and not v.startswith("POS"):
            return v
    if e.get("r08b", {}).get("lr_cruise"):
        return e["r08b"]["lr_cruise"]
    return None


def datasets_of(inv: dict) -> list[dict]:
    """One row per (pair, side) with the identifier that names the source dataset."""
    rows = []
    for e in inv["entries"]:
        if not e["in_corpus"]:
            continue
        pid, m = e["pair_id"], e["manifest"] or {}
        rm = e.get("raw_metadata") or {}
        # ---- HR side
        hr_doi = (rm.get("hr") or {}).get("doi") or (m.get("hr_doi") or "")
        if e.get("mgds"):
            uid = e["mgds"]["uid"]
            doi = e["mgds"].get("doi") or (hr_doi if hr_doi.startswith("10.") else None)
            rows.append({"pair_id": pid, "side": "hr", "provider": "MGDS", "id": f"MGDS:{uid}", "doi": doi, "mgds_uid": uid,
                         "title": e["mgds"].get("title"), "landing": f"https://www.marine-geo.org/tools/search/entry.php?id=MGDS:{uid}"})
        elif hr_doi.startswith("10."):
            prov = "PANGAEA" if "PANGAEA" in hr_doi else ("USGS" if hr_doi.startswith("10.5066") else "DOI")
            rows.append({"pair_id": pid, "side": "hr", "provider": prov, "id": hr_doi, "doi": hr_doi, "title": None, "landing": f"https://doi.org/{hr_doi}"})
        else:
            rows.append({"pair_id": pid, "side": "hr", "provider": m.get("hr_platform") or "unknown", "id": hr_doi or "none", "doi": None, "title": None, "landing": None})
        # ---- LR side
        lr_doi = (rm.get("lr") or {}).get("doi") or (m.get("lr_doi") or "")
        if lr_doi.startswith("10."):
            prov = "PANGAEA" if "PANGAEA" in lr_doi else ("USGS" if lr_doi.startswith("10.5066") else "DOI")
            rows.append({"pair_id": pid, "side": "lr", "provider": prov, "id": lr_doi, "doi": lr_doi, "title": None, "landing": f"https://doi.org/{lr_doi}"})
        else:
            cruise = ncei_cruise_from_entry(e)
            rows.append({"pair_id": pid, "side": "lr", "provider": "NCEI", "id": f"NCEI:{cruise}", "doi": None, "cruise": cruise, "title": None,
                         "landing": NCEI_ISO.format(cruise=cruise) if cruise else None})
    return rows


def main():
    inv = C.jload(C.INVENTORY)
    CACHE.mkdir(parents=True, exist_ok=True)
    rows = datasets_of(inv)
    audited: dict[str, dict] = {}
    for r in rows:
        key = r["id"]
        if key in audited:
            continue
        rec = {"id": key, "provider": r["provider"], "doi": r.get("doi"), "landing": r.get("landing"), "title": r.get("title")}
        if r["provider"] == "NCEI":
            n = ncei(r["cruise"]) if r.get("cruise") else {"found": False}
            rec.update(found=n.get("found", False), title=n.get("title"), evidence=n.get("source"),
                       license="U.S. Government work, public domain (NOAA NCEI Multibeam Bathymetry Database); NCEI constraints are liability and not-for-navigation disclaimers" if n.get("found") else "NCEI ISO record not retrieved",
                       redistribution="yes" if n.get("found") else "confirm", restriction_codes=n.get("restriction_codes"), constraint_texts=n.get("constraint_texts"))
        else:
            doi = r.get("doi")
            dc = datacite(doi) if doi else None
            if (dc is None or not dc.get("found")) and r.get("mgds_uid"):
                for pat in MGDS_PREFIXES:
                    cand = pat.format(uid=r["mgds_uid"])
                    dc = datacite(cand)
                    if dc and dc.get("found"):
                        rec["doi"] = cand
                        C.fix("license_audit", r["pair_id"], f"MGDS:{r['mgds_uid']} had no DOI in the manifest/harvest; resolved {cand} on DataCite")
                        break
            if dc and dc.get("found"):
                lic, red = classify(dc.get("rightsList") or [])
                rec.update(found=True, title=dc.get("title"), creators=dc.get("creators"), publisher=dc.get("publisher"), year=dc.get("publicationYear"),
                           evidence=dc.get("source"), rights=dc.get("rightsList"), license=lic, redistribution=red, landing=dc.get("url") or rec["landing"])
                if red == "confirm" and r["provider"] == "USGS":
                    fg = usgs_fgdc(doi)
                    if fg and fg.get("found") and fg.get("useconst") and re.search(r"public domain", fg["useconst"], re.I):
                        rec.update(license="U.S. Government work, public domain (USGS data release; FGDC use constraints: freely redistributable with attribution to USGS and MBARI; not for navigation)",
                                   redistribution="yes", evidence=fg["source"], rights=[{"rights": fg["useconst"][:300]}])
                        C.fix("license_audit", r["pair_id"], f"{doi}: DataCite record has no rightsList; license read from the FGDC metadata linked on the CMGDS landing page")
            elif r["provider"] == "MGDS" and mgds_landing(r["mgds_uid"]).get("license"):
                lp = mgds_landing(r["mgds_uid"])
                lic, red = classify([{"rights": lp["license"]}])
                rec.update(found=True, title=lp.get("title") or rec.get("title"), evidence=lp["source"], rights=[{"rights": lp["license"], "source": "schema.org JSON-LD on the MGDS data set page"}],
                           license=f"{lp['license']} (stated on the MGDS data set page; no DOI record)", redistribution=red, landing=lp["source"])
                C.fix("license_audit", r["pair_id"], f"MGDS:{r['mgds_uid']} has no DOI record; license '{lp['license']}' read from the data set page's schema.org metadata (ruling 2026-10-20)")
            else:
                rec.update(found=False, evidence=rec.get("landing"), rights=[],
                           license="no DOI record found; MGDS default terms (CC BY-NC-SA, per MGDS data policy; ACQ-R08 H-3)" if r["provider"] == "MGDS" else "no DOI record found",
                           redistribution="confirm")
        audited[key] = rec
        C.log(f"  {key:32s} {rec['provider']:8s} {rec['redistribution']:16s} {rec['license'][:70]}")
    # per-pair effective license
    per_pair = {}
    for e in inv["entries"]:
        if not e["in_corpus"]:
            continue
        ids = [r["id"] for r in rows if r["pair_id"] == e["pair_id"]]
        reds = [audited[i]["redistribution"] for i in ids]
        lics = [audited[i]["license"] for i in ids]
        # Ruling 2026-10-20 (H-1 option b): the whole record, every pair and the corpus-level files are CC BY-NC-SA 4.0.
        # `status` keeps the source audit result; `sources_cc_by_or_public_domain_only` tells users which pairs come only from
        # CC BY / public-domain sources (and could be reused under those terms directly from the sources).
        if "no" in reds:
            status = "no"
        elif "yes_conditional" in reds:
            status = "yes_conditional"
        elif "confirm" in reds:
            status = "confirm"
        else:
            status = "yes"
        per_pair[e["pair_id"]] = {"sources": ids, "source_licenses": lics, "pair_license": RECORD_LICENSE, "status": status,
                                  "sources_cc_by_or_public_domain_only": status == "yes"}
    out = {"generated": C.utcnow(), "datasets": audited, "per_pair": per_pair, "rows": rows}
    C.jdump(out, C.LICENSE_AUDIT)
    with open(C.RPT / "license_audit.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset_id", "provider", "doi", "title", "license", "redistribution_allowed", "evidence", "n_pairs"])
        for k, rec in audited.items():
            w.writerow([k, rec["provider"], rec.get("doi") or "", (rec.get("title") or "")[:140], rec["license"], rec["redistribution"], rec.get("evidence") or "",
                        sum(1 for r in rows if r["id"] == k)])
    from collections import Counter
    C.log(f"license audit: {len(audited)} datasets; redistribution {dict(Counter(r['redistribution'] for r in audited.values()))}; "
          f"pairs {dict(Counter(v['status'] for v in per_pair.values()))} -> {C.LICENSE_AUDIT}")


if __name__ == "__main__":
    main()
