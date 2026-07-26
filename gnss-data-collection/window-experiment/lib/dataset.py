#!/usr/bin/env python3
"""
dataset.py -- one catalog + one loader for ALL gesture data, across strands.

The gesture captures live in two places, in three different on-disk naming
schemes, only some with meta sidecars or manifests:

  window-experiment/data/samples/   rich: <gesture>_W<win>-<date>-<time>Z.rtcm
                                     + .meta.json sidecar + <session>_manifest.json
                                     mixed observable: MSM7 and RAWX (see below)
  window-experiment/data/archive/*  older/variant window-experiment sessions
  finesat/data/samples/ (+ jn18*/)   raw: <gesture>-<date>-<time>.rtcm only
                                     no meta, no manifest, MSM7, no window control

This module hides those differences behind a single interface:
  - catalog()               -> one index record per session (provenance + shape)
  - load_session(name)       -> uniform per-capture records
  - load(...)                -> multi-session load with filters
  - parse(capture, ...)      -> phases (+ geometry) via the geomlib primitives

THE HARD RULE IT ENFORCES: never *silently* pool MSM7 and RAWX observables
(their phase is reconstructed differently; the project treats a blind pool as a
bug). load() raises if a selection spans >1 observable unless you say so
explicitly (observable=... or allow_mixed_observable=True). Campaign mixing
(window-experiment vs finesat) is flagged the same way.

Breathing data is a DIFFERENT sensing task (different rig, filenames, and goal)
and is intentionally NOT catalogued here.

CLI:  uv run window-experiment/lib/dataset.py            # print the catalog
      uv run window-experiment/lib/dataset.py --dump     # also write CATALOG.json
"""
from __future__ import annotations

import os
import re
import sys
import json
import glob
from dataclasses import dataclass, field, asdict

_HERE = os.path.dirname(os.path.abspath(__file__))          # .../window-experiment/lib
_WE = os.path.dirname(_HERE)                                 # .../window-experiment
_GNSS = os.path.dirname(_WE)                                 # .../gnss-data-collection
sys.path.insert(0, _HERE)                                    # geomlib / parse_rawx

WE_SAMPLES = os.path.join(_WE, "data", "samples")
WE_ARCHIVE = os.path.join(_WE, "data", "archive")
FS_SAMPLES = os.path.join(_GNSS, "finesat", "data", "samples")
FS_ARCHIVE = os.path.join(_GNSS, "finesat", "data", "archive")

# finesat filename: <gesture>-<YYMMDD>-<HHMM[SS]>.rtcm   (no window/rep/'Z';
# the "wo_sec" archive set drops seconds -> accept 4- or 6-digit time)
_FS_RE = re.compile(r"^([A-Za-z]+)-(\d{6})-(\d{4,6})\.rtcm$")
# (window-experiment captures are read via their manifests, not filename parsing)


@dataclass
class Session:
    name: str
    campaign: str          # "window-experiment" | "finesat"
    observable: str        # "MSM7" | "RAWX"
    source_key: str        # "msm" | "rawx"  (for geomlib dispatch)
    windowed: bool         # timed window control (W0..W3) vs ad-hoc
    has_meta: bool         # .meta.json sidecars present (geometry available)
    has_manifest: bool
    archived: bool
    gestures: list = field(default_factory=list)
    windows: list = field(default_factory=list)
    n_captures: int = 0
    sample_dir: str = ""
    manifest_path: str | None = None


def _detect_observable(rtcm_path):
    """Determine observable from the DATA, not the name/era: RAWX if the stream
    carries UBX-RXM-RAWX, else MSM7 (reconstructed from RTCM 1077/1127). Probing
    the file is the only reliable signal -- RAWX appeared as early as Jun-26, so
    date/archive heuristics mislabel it (e.g. ref_jun26_pm is RAWX)."""
    from pyubx2 import UBXReader, UBX_PROTOCOL, NMEA_PROTOCOL, RTCM3_PROTOCOL
    try:
        with open(rtcm_path, "rb") as fh:
            for _r, p in UBXReader(fh, protfilter=UBX_PROTOCOL | NMEA_PROTOCOL | RTCM3_PROTOCOL):
                if p is not None and getattr(p, "identity", None) == "RXM-RAWX":
                    return "RAWX", "rawx"      # early-exit on first RAWX record
    except Exception:
        pass
    return "MSM7", "msm"


def _dir_has_meta(d):
    return bool(glob.glob(os.path.join(d, "*.meta.json")))


def _we_session_from_manifest(mpath, archived):
    m = json.load(open(mpath))
    name = m.get("session") or os.path.basename(mpath).replace("_manifest.json", "")
    entries = m.get("entries", [])
    sdir = os.path.dirname(mpath)
    obs, src = _detect_observable(os.path.join(sdir, entries[0]["rtcm"])) if entries else ("MSM7", "msm")
    gestures = sorted({e["gesture"] for e in entries})
    windows = sorted({e["window_index"] for e in entries})
    return Session(
        name=name, campaign="window-experiment", observable=obs, source_key=src,
        windowed=bool(windows), has_meta=_dir_has_meta(os.path.dirname(mpath)),
        has_manifest=True, archived=archived, gestures=gestures, windows=windows,
        n_captures=len(entries), sample_dir=os.path.dirname(mpath), manifest_path=mpath,
    )


def _fs_session_from_dir(d, name):
    rtcms = sorted(glob.glob(os.path.join(d, "*.rtcm")))
    gestures = sorted({m.group(1) for m in (_FS_RE.match(os.path.basename(f)) for f in rtcms) if m})
    obs, src = _detect_observable(rtcms[0]) if rtcms else ("MSM7", "msm")
    return Session(
        name=name, campaign="finesat", observable=obs, source_key=src,
        windowed=False, has_meta=_dir_has_meta(d), has_manifest=False, archived="archive" in d,
        gestures=gestures, windows=[], n_captures=len(rtcms), sample_dir=d, manifest_path=None,
    )


def _fs_name(subdir):
    """Session id for a finesat subdirectory (drop the redundant 'samples-' prefix)."""
    base = os.path.basename(subdir.rstrip("/"))
    base = base[len("samples-"):] if base.startswith("samples-") else base
    return "finesat_" + base


_CATALOG_CACHE = None


def catalog(refresh=False):
    """Return the list of Session records for every gesture session (cached)."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None and not refresh:
        return _CATALOG_CACHE
    sessions = []
    # window-experiment: active + archived (manifest-driven)
    for mpath in sorted(glob.glob(os.path.join(WE_SAMPLES, "*_manifest.json"))):
        sessions.append(_we_session_from_manifest(mpath, archived=False))
    for mpath in sorted(glob.glob(os.path.join(WE_ARCHIVE, "*", "*_manifest.json"))):
        sessions.append(_we_session_from_manifest(mpath, archived=True))
    # finesat: one session per directory (no manifests)
    if glob.glob(os.path.join(FS_SAMPLES, "*.rtcm")):
        sessions.append(_fs_session_from_dir(FS_SAMPLES, "finesat_main"))
    for sub in sorted(glob.glob(os.path.join(FS_SAMPLES, "*/"))):
        sessions.append(_fs_session_from_dir(sub, _fs_name(sub)))
    for sub in sorted(glob.glob(os.path.join(FS_ARCHIVE, "*/"))):
        sessions.append(_fs_session_from_dir(sub, _fs_name(sub)))
    dups = {s.name for s in sessions if [x.name for x in sessions].count(s.name) > 1}
    if dups:
        raise ValueError(f"catalog has colliding session names {sorted(dups)} -- "
                         "session ids must be unique; disambiguate the manifest 'session' fields")
    _CATALOG_CACHE = sessions
    return sessions


def get_session(name):
    for s in catalog():
        if s.name == name:
            return s
    raise KeyError(f"no gesture session named {name!r}. Known: {[s.name for s in catalog()]}")


def load_session(name):
    """Return a list of uniform capture records for one session.

    Each record: {session, campaign, observable, source_key, gesture, window,
    rep, utc, rtcm_path, meta_path}.  window/rep/utc are None when the source
    doesn't record them (finesat)."""
    s = get_session(name)
    out = []
    if s.has_manifest:
        m = json.load(open(s.manifest_path))
        for e in m.get("entries", []):
            rtcm = os.path.join(s.sample_dir, e["rtcm"])
            meta = os.path.join(s.sample_dir, e["meta"]) if e.get("meta") else None
            out.append(dict(
                session=s.name, campaign=s.campaign, observable=s.observable,
                source_key=s.source_key, gesture=e["gesture"], window=e.get("window_index"),
                rep=e.get("rep"), utc=e.get("actual_utc"), rtcm_path=rtcm,
                meta_path=meta if (meta and os.path.exists(meta)) else None,
            ))
    else:  # finesat: parse the filename
        for f in sorted(glob.glob(os.path.join(s.sample_dir, "*.rtcm"))):
            mm = _FS_RE.match(os.path.basename(f))
            if not mm:
                continue
            gesture, d, t = mm.groups()
            sec = t[4:6] if len(t) == 6 else "00"
            out.append(dict(
                session=s.name, campaign=s.campaign, observable=s.observable,
                source_key=s.source_key, gesture=gesture, window=None, rep=None,
                utc=f"20{d[:2]}-{d[2:4]}-{d[4:6]}T{t[:2]}:{t[2:4]}:{sec}Z",
                rtcm_path=f, meta_path=None,
            ))
    return out


def load(sessions=None, campaign=None, observable=None, gestures=None,
         archived=False, allow_mixed_observable=False, allow_mixed_campaign=False):
    """Load capture records across sessions, with the no-silent-pool guard.

    sessions: explicit names (default: all matching the other filters).
    campaign/observable/gestures: filters. archived=True to include archives.
    Raises ValueError if the selection spans >1 observable (or >1 campaign)
    unless you opt in explicitly -- this is the guard against silently pooling
    MSM7 with RAWX (the project's hard rule)."""
    cat = catalog()
    if sessions is not None:
        chosen = [get_session(n) for n in sessions]
    else:
        chosen = [s for s in cat if (archived or not s.archived)]
    if campaign:
        chosen = [s for s in chosen if s.campaign == campaign]
    if observable:
        chosen = [s for s in chosen if s.observable == observable]
    if not chosen:
        raise ValueError("no sessions match the given filters")

    obs = {s.observable for s in chosen}
    if len(obs) > 1 and not allow_mixed_observable:
        raise ValueError(
            f"selection spans multiple observables {sorted(obs)} -- refusing to "
            f"silently pool MSM7 and RAWX. Pass observable='MSM7'|'RAWX' to pick one, "
            f"or allow_mixed_observable=True to override deliberately.\n  sessions: "
            + ", ".join(f"{s.name}({s.observable})" for s in chosen))
    camps = {s.campaign for s in chosen}
    if len(camps) > 1 and not allow_mixed_campaign:
        raise ValueError(
            f"selection spans multiple campaigns {sorted(camps)} (different collection "
            f"protocols). Pass campaign=... to pick one, or allow_mixed_campaign=True.\n"
            "  sessions: " + ", ".join(f"{s.name}({s.campaign})" for s in chosen))

    recs = []
    for s in chosen:
        for r in load_session(s.name):
            if gestures and r["gesture"] not in gestures:
                continue
            recs.append(r)
    return recs


def parse(capture, with_geometry=False, normalize_labels=True):
    """Parse one capture record into phases (and optionally geometry).

    Dispatches to the correct geomlib primitive by observable. Returns
    {phases, locktime, [los, elev, ref_sat]}. Geometry requires a meta sidecar
    (window-experiment only); with_geometry on a finesat capture raises."""
    import geomlib  # lazy: pulls in pyubx2
    ph, lk = (geomlib.parse_msm if capture["source_key"] == "msm"
              else geomlib.parse_rawx_ph)(capture["rtcm_path"])
    out = dict(phases=ph, locktime=lk)
    if with_geometry:
        if not capture.get("meta_path"):
            raise ValueError(f"{capture['session']}/{capture['gesture']}: no meta "
                             "sidecar -> geometry (los_enu/elev) unavailable")
        los, el, ref = geomlib.load_meta(capture["rtcm_path"])
        out.update(los=los, elev=el, ref_sat=ref)
    return out


# canonical filename scheme for FUTURE captures (session-encoding, self-identifying)
CANONICAL_NAME = "<session>__<gesture>_W<window>_r<rep>__<UTCYYYYMMDDTHHMMSSZ>.{rtcm,meta.json}"


def _print_catalog():
    cat = catalog()
    nw = max(len("session"), max(len(s.name) for s in cat)) + 2
    hdr = f"{'session':<{nw}}{'campaign':<18}{'obs':<6}{'win':<5}{'meta':<6}{'arch':<6}{'n':>5}  gestures / windows"
    print(hdr)
    print("-" * len(hdr))
    for camp in ("window-experiment", "finesat"):
        for s in [x for x in cat if x.campaign == camp]:
            g = ",".join(s.gestures) if s.gestures else "-"
            w = str(s.windows) if s.windows else "-"
            print(f"{s.name:<{nw}}{s.campaign:<18}{s.observable:<6}"
                  f"{('Y' if s.windowed else '-'):<5}{('Y' if s.has_meta else '-'):<6}"
                  f"{('Y' if s.archived else '-'):<6}{s.n_captures:>5}  {g}  |  W{w}")
    tot = sum(s.n_captures for s in cat)
    print("-" * len(hdr))
    print(f"{len(cat)} gesture sessions, {tot} captures.  "
          f"MSM7={sum(s.n_captures for s in cat if s.observable=='MSM7')}  "
          f"RAWX={sum(s.n_captures for s in cat if s.observable=='RAWX')}")
    print(f"canonical future-capture name: {CANONICAL_NAME}")


if __name__ == "__main__":
    _print_catalog()
    if "--dump" in sys.argv:
        out = os.path.join(_WE, "data", "CATALOG.json")
        json.dump([asdict(s) for s in catalog()], open(out, "w"), indent=2)
        print(f"\nwrote {out}")
