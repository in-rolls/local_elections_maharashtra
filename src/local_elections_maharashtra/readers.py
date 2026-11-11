"""How cells are read and normalised. Shared by admission, the release build and the checks."""

import io
import re

import pandas as pd
from lxml import html as lxml_html

from local_elections_maharashtra.paths import MANUAL

# Seat reservation as the SEC prints it -> (reserved_caste, reserved_woman).
# The fold follows central canon.py (Maharashtra uses scheme sc_st_obc); "(W)" marks a seat
# reserved for a woman.
RESERVATION = {
    "GEN": ("NONE", 0),
    "GEN(W)": ("NONE", 1),
    "S.C.": ("SC", 0),
    "S.C.(W)": ("SC", 1),
    "S.T.": ("ST", 0),
    "S.T.(W)": ("ST", 1),
    "B.C.C.": ("BC", 0),
    "B.C.C.(W)": ("BC", 1),
}
LABEL = {
    ("NONE", 0): "Other than Woman",
    ("NONE", 1): "Woman",
    ("SC", 0): "SC Other than Woman",
    ("SC", 1): "SC Woman",
    ("ST", 0): "ST Other than Woman",
    ("ST", 1): "ST Woman",
    ("BC", 0): "BC Other than Woman",
    ("BC", 1): "BC Woman",
}
# The candidate's own category as printed -> pooled value.
CANDIDATE_CASTE = {"GEN": "NONE", "SC": "SC", "ST": "ST", "B.C.C": "BC"}
CANDIDATE_WOMAN = {"Female": 1, "Male": 0}

GP_PREFIX = r"^(grampanchayat|grampan|gp)"
GP_SUFFIX = r"(gramapanchayat|grampanchayat|grampanchayt|grampanchyat|grampanchaya|grampancha|gp)$"


def nk(value) -> str:
    """Lower-case letters and digits only. Used inside join keys, never released."""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def tidy(value) -> str:
    """Whitespace only: runs of spaces, tabs or newlines become one space; edges trimmed."""
    return re.sub(r"\s+", " ", str(value)).strip()


def gp_key(value) -> str:
    """GP name in the join key: prefixes and suffixes such as GP or Grampanchayat removed."""
    full = nk(value)
    short = re.sub(GP_SUFFIX, "", re.sub(GP_PREFIX, "", full))
    short = re.sub(r"khurd$", "kh", re.sub(r"budruk$", "bk", short))
    return short if len(short) >= 3 else full


def aliases() -> tuple[dict, dict]:
    """District and taluka renames from data/manual/aliases.csv: printed -> joined_as."""
    table = pd.read_csv(MANUAL / "aliases.csv", dtype=str)
    district = dict(table.loc[table["level"] == "district", ["printed", "joined_as"]].values)
    taluka = dict(table.loc[table["level"] == "taluka", ["printed", "joined_as"]].values)
    return district, taluka


def read_table(data: bytes) -> tuple[pd.DataFrame, str, int]:
    """Every cell of the first table as the text stored in the file.

    Returns the table, the file format and the number of tables (HTML) or sheets (Excel).
    The SEC portal serves UTF-16 HTML tables with an .xls name; some copies are real Excel
    files, whose numbers are read as the spreadsheet displays them (whole numbers without .0).
    """
    if data[:2] == b"\xff\xfe":
        doc = lxml_html.fromstring(data.decode("utf-16", "ignore"))
        n_tables = len(doc.xpath("//table"))
        rows = doc.xpath("(//table)[1]//tr")
        cells = [[c.text_content() for c in r.xpath("./th|./td")] for r in rows]
        head = [h.strip() for h in cells[0]]
        body = [
            r + [""] * (len(head) - len(r)) if len(r) < len(head) else r[: len(head)]
            for r in cells[1:]
        ]
        return pd.DataFrame(body, columns=head), "utf16_html", n_tables
    engine = "xlrd" if data[:4] == b"\xd0\xcf\x11\xe0" else None
    book = pd.ExcelFile(io.BytesIO(data), engine=engine)
    table = book.parse(book.sheet_names[0], dtype=object, keep_default_na=False)
    table.columns = [str(c).strip() for c in table.columns]
    table = table.map(
        lambda v: str(int(v)) if isinstance(v, float) and v.is_integer() else ("" if v is None else str(v))
    )
    return table, ("xls_biff" if engine else "xlsx"), len(book.sheet_names)


def kind_of(columns) -> str | None:
    """Which SEC report a table is, from its header."""
    cols = set(columns)
    if "Partyname" in cols:
        return "winner_report"
    if {"Rank", "Total Votes Secured"} <= cols:
        return "counting"
    if {"Reservation", "Ward Name", "Male Voters"} <= cols and "Rank" not in cols:
        return "ward_seat"
    return None


def sarpanch_mask(table: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(sarpanch rows, ward 999 rows, rows in a programme named for sarpanch)."""
    ward = "Ward No." if "Ward No." in table.columns else "Ward No"
    is_999 = table[ward].str.strip() == "999"
    sarpanch_programme = table["Election Program Name"].str.contains("sarpan", case=False)
    return is_999 & sarpanch_programme, is_999, sarpanch_programme
