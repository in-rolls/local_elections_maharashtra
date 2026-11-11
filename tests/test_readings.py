"""How cells are read: these rules decide every released value."""

import pandas as pd

from local_elections_maharashtra.readers import (
    RESERVATION,
    gp_key,
    kind_of,
    nk,
    read_table,
    sarpanch_mask,
    tidy,
)


def utf16_table(header, rows):
    cells = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    head = "<tr>" + "".join(f"<th>{h}</th>" for h in header) + "</tr>"
    return ("﻿<html><body><table>" + head + cells + "</table></body></html>").encode("utf-16-le")


def test_tidy_changes_whitespace_only():
    assert tidy("\tGram Pan\tAsgoli ") == "Gram Pan Asgoli"
    assert tidy("  May 2018  Gram panchayat sARPANCH ") == "May 2018 Gram panchayat sARPANCH"


def test_gp_key_drops_prefixes_and_suffixes():
    assert gp_key("Gumgaon GP") == gp_key("Gumgaon") == "gumgaon"
    assert gp_key("Gram Pan Asgoli") == "asgoli"
    assert gp_key("Wadsa Khurd") == gp_key("Wadsa Kh.")
    assert gp_key("GP") == "gp"  # never reduced below three letters


def test_reservation_codes():
    assert RESERVATION["B.C.C.(W)"] == ("BC", 1)
    assert RESERVATION["GEN"] == ("NONE", 0)
    assert "NULL" not in RESERVATION


def test_read_table_keeps_cells_as_printed():
    data = utf16_table(["Election Program Name", "Ward No.", "Name of Contesting Candidate", "Total Votes Secured", "Rank"],
                       [["7751 Grampanchayat Sarpanch General Election", "999", " ASHA  PATIL ", "0540", "1"]])
    table, fmt, n_tables = read_table(data)
    assert fmt == "utf16_html" and n_tables == 1
    assert table.iloc[0]["Name of Contesting Candidate"] == " ASHA  PATIL "
    assert table.iloc[0]["Total Votes Secured"] == "0540"
    assert kind_of(table.columns) == "counting"


def test_sarpanch_rows_need_ward_999_and_a_sarpanch_programme():
    table = pd.DataFrame({"Election Program Name": ["GP Sarpanch Election", "GP Sarpanch Election", "GP Member Election"],
                          "Ward No.": ["999", "3", "999"]})
    keep, _, _ = sarpanch_mask(table)
    assert keep.tolist() == [True, False, False]
    assert nk("S.C.(W)") == "scw"
