
"""Download and maintain SmartStock's combined NSE + BSE equity master.

NSE source: official NSE equity-segment CSV.
BSE source: official BSE scrip master ZIP (SCRIP.ZIP).
The existing local master is retained if an exchange download fails.
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
import zipfile

import pandas as pd
import requests

NSE_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
BSE_URL = "https://www.bseindia.com/downloads/Help/file/scrip.zip"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept": "text/csv,application/zip,*/*",
    "Referer": "https://www.nseindia.com/",
}

MASTER_COLUMNS = [
    "SYMBOL", "NAME OF COMPANY", " SERIES", " DATE OF LISTING",
    " PAID UP VALUE", " MARKET LOT", " ISIN NUMBER", " FACE VALUE",
    "EXCHANGE", "SECURITY_CODE",
]


def _clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [str(c).replace("\ufeff", "").strip() for c in df.columns]
    return df


def _first_column(df: pd.DataFrame, candidates: list[str], default=""):
    lookup = {str(c).strip().upper(): c for c in df.columns}
    for candidate in candidates:
        if candidate.upper() in lookup:
            return df[lookup[candidate.upper()]]
    return pd.Series([default] * len(df), index=df.index)


def _download(url: str, session: requests.Session) -> bytes:
    response = session.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    if not response.content:
        raise ValueError("The exchange returned an empty file.")
    return response.content


def fetch_nse_equities(session: requests.Session | None = None) -> pd.DataFrame:
    session = session or requests.Session()
    raw = _download(NSE_URL, session)
    df = pd.read_csv(BytesIO(raw), dtype=str)
    df = _clean_columns(df)

    symbol = _first_column(df, ["SYMBOL"])
    name = _first_column(df, ["NAME OF COMPANY", "COMPANY NAME"])
    series = _first_column(df, [" SERIES", "SERIES"])
    listing = _first_column(df, [" DATE OF LISTING", "DATE OF LISTING"])
    paid = _first_column(df, [" PAID UP VALUE", "PAID UP VALUE"])
    lot = _first_column(df, [" MARKET LOT", "MARKET LOT"], "1")
    isin = _first_column(df, [" ISIN NUMBER", "ISIN NUMBER", "ISIN"])
    face = _first_column(df, [" FACE VALUE", "FACE VALUE"])

    result = pd.DataFrame({
        "SYMBOL": symbol, "NAME OF COMPANY": name,
        " SERIES": series, " DATE OF LISTING": listing,
        " PAID UP VALUE": paid, " MARKET LOT": lot,
        " ISIN NUMBER": isin, " FACE VALUE": face,
        "EXCHANGE": "NSE", "SECURITY_CODE": "",
    })
    result["SYMBOL"] = result["SYMBOL"].astype(str).str.strip()
    result = result[result["SYMBOL"].ne("") & result["SYMBOL"].ne("nan")]
    result = result[result[" SERIES"].astype(str).str.strip().str.upper().isin(["EQ", "BE", "BZ", "SM", "ST", "SZ", "E1", "E2"])]
    return result


def _read_bse_file(raw: bytes) -> pd.DataFrame:
    """Read BSE's ZIP master, supporting named columns and documented fixed positions."""
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
        candidates = [n for n in archive.namelist() if n.lower().endswith((".csv", ".txt"))]
        if not candidates:
            raise ValueError("No CSV/TXT file found inside BSE scrip ZIP.")
        payload = archive.read(candidates[0])
    except zipfile.BadZipFile:
        payload = raw

    last_error = None
    for encoding in ("utf-8-sig", "latin1"):
        try:
            # First try a normal header row.
            frame = pd.read_csv(BytesIO(payload), dtype=str, encoding=encoding)
            frame = _clean_columns(frame)
            known_headers = {
                "SCRIP CODE", "SCRIPCODE", "INSTRUMENT CODE",
                "ISIN CODE", "ISIN", "SECURITY TYPE FLAG"
            }
            if known_headers.intersection({str(c).strip().upper() for c in frame.columns}):
                return frame

            # Some daily BSE masters are headerless; re-read without consuming row 1.
            frame = pd.read_csv(BytesIO(payload), dtype=str, encoding=encoding, header=None)
            if len(frame.columns) >= 8:
                return frame
        except Exception as exc:
            last_error = exc
    raise ValueError(f"Could not parse BSE scrip master: {last_error}")


def fetch_bse_equities(session: requests.Session | None = None) -> pd.DataFrame:
    session = session or requests.Session()
    raw = _download(BSE_URL, session)
    df = _read_bse_file(raw)

    # BSE's documented standardized master fields include:
    # Scrip Code, Instrument Code, Group Name, Scrip Name, ISIN CODE,
    # Market Lot, Face Value (in paisa), Security Type Flag.
    named = {str(c).strip().upper(): c for c in df.columns}
    if any(k in named for k in ("SCRIP CODE", "SCRIPCODE", "ISIN CODE", "ISIN")):
        code = _first_column(df, ["Scrip Code", "ScripCode", "Security Code"])
        symbol = _first_column(df, ["Instrument Code", "Trading Symbol", "Symbol"])
        group = _first_column(df, ["Group Name", "Group", "Series"])
        name = _first_column(df, ["Scrip Name", "Security Name", "Company Name"])
        isin = _first_column(df, ["ISIN CODE", "ISIN"])
        lot = _first_column(df, ["Market Lot", "MarketLot"], "1")
        face = _first_column(df, ["Face Value", "FaceValue"])
        security_type = _first_column(df, ["Security Type Flag", "SecurityType"])
    else:
        # Standard BSE_EQ_SCRIP_DDMMYYYY.csv layout, fields 1-8.
        if len(df.columns) < 8:
            raise ValueError("BSE master does not contain the documented security fields.")
        code, symbol, group, name, isin, lot, face, security_type = [df.iloc[:, i] for i in range(8)]

    result = pd.DataFrame({
        "SYMBOL": symbol, "NAME OF COMPANY": name,
        " SERIES": group, " DATE OF LISTING": "",
        " PAID UP VALUE": "", " MARKET LOT": lot,
        " ISIN NUMBER": isin, " FACE VALUE": face,
        "EXCHANGE": "BSE", "SECURITY_CODE": code,
    })
    result["SYMBOL"] = result["SYMBOL"].fillna("").astype(str).str.strip()
    result["NAME OF COMPANY"] = result["NAME OF COMPANY"].fillna("").astype(str).str.strip()
    result[" ISIN NUMBER"] = result[" ISIN NUMBER"].fillna("").astype(str).str.strip()
    result = result[
        result["SYMBOL"].ne("") &
        result["NAME OF COMPANY"].ne("") &
        security_type.fillna("").astype(str).str.strip().str.upper().eq("EQ")
    ].copy()
    # BSE master stores face value in paise; convert to rupees.
    face_num = pd.to_numeric(result[" FACE VALUE"], errors="coerce")
    result[" FACE VALUE"] = face_num.div(100).where(face_num.notna(), result[" FACE VALUE"])
    return result


def _normalise_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=MASTER_COLUMNS)
    old = pd.read_csv(path, dtype=str)
    old = _clean_columns(old)
    # Restore the legacy column labels used by the original NSE CSV.
    rename = {
        "SERIES": " SERIES", "DATE OF LISTING": " DATE OF LISTING",
        "PAID UP VALUE": " PAID UP VALUE", "MARKET LOT": " MARKET LOT",
        "ISIN NUMBER": " ISIN NUMBER", "FACE VALUE": " FACE VALUE",
    }
    old = old.rename(columns=rename)
    for col in MASTER_COLUMNS:
        if col not in old.columns:
            old[col] = ""
    old["EXCHANGE"] = old["EXCHANGE"].replace("", pd.NA).fillna("NSE").str.upper()
    old["SYMBOL"] = old["SYMBOL"].fillna("").astype(str).str.strip()
    old[" ISIN NUMBER"] = old[" ISIN NUMBER"].fillna("").astype(str).str.strip()
    return old[MASTER_COLUMNS]


def refresh_stock_master(csv_path: str | Path = "stocks.csv") -> dict:
    """Refresh exchanges independently; retain old records for failed sources."""
    path = Path(csv_path)
    existing = _normalise_existing(path)
    session = requests.Session()
    messages = {}
    downloaded = []

    for exchange, fetcher in (("NSE", fetch_nse_equities), ("BSE", fetch_bse_equities)):
        try:
            fresh = fetcher(session)
            if fresh.empty:
                raise ValueError("The downloaded file contained no equity rows.")
            downloaded.append(fresh)
            messages[exchange] = f"Downloaded {len(fresh):,} equity records."
        except Exception as exc:
            messages[exchange] = f"Refresh failed; kept existing {exchange} records. Reason: {exc}"

    if not downloaded:
        raise RuntimeError("Neither exchange master could be downloaded. Your existing stocks.csv was not changed. " + " ".join(messages.values()))

    combined = pd.concat([existing] + downloaded, ignore_index=True)
    combined["EXCHANGE"] = combined["EXCHANGE"].fillna("NSE").astype(str).str.upper()
    combined["SYMBOL"] = combined["SYMBOL"].fillna("").astype(str).str.strip()
    combined[" ISIN NUMBER"] = combined[" ISIN NUMBER"].fillna("").astype(str).str.strip()

    # Deduplicate by exchange + security code when available, otherwise exchange + symbol + ISIN.
    combined["SECURITY_CODE"] = combined["SECURITY_CODE"].fillna("").astype(str).str.strip()
    combined["_KEY"] = combined.apply(
        lambda r: f"{r['EXCHANGE']}|CODE|{r['SECURITY_CODE']}" if r["SECURITY_CODE"] else
                  f"{r['EXCHANGE']}|{r['SYMBOL']}|{r[' ISIN NUMBER']}", axis=1
    )
    combined = combined.drop_duplicates("_KEY", keep="last").drop(columns="_KEY")

    # Stable, familiar ordering; retain all legacy fields for compatibility.
    combined = combined[MASTER_COLUMNS]
    combined = combined.sort_values(["EXCHANGE", "SYMBOL"], kind="stable").reset_index(drop=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(path.stem + ".tmp" + path.suffix)
    combined.to_csv(temp_path, index=False)
    temp_path.replace(path)

    return {
        "total": len(combined),
        "nse": int((combined["EXCHANGE"] == "NSE").sum()),
        "bse": int((combined["EXCHANGE"] == "BSE").sum()),
        "messages": messages,
        "updated_at": datetime.now().strftime("%d-%b-%Y %I:%M %p"),
    }


def load_stock_master(csv_path: str | Path = "stocks.csv") -> pd.DataFrame:
    return _normalise_existing(Path(csv_path))
