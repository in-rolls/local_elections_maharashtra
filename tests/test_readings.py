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


def _seats(rows):
    cols = ["Election Program Name", "LocalBody Name", "District", "Taluka", "Ward No", "Ward Name", "Reservation",
            "Male Voters", "Female Voters", "Other Voters", "No. of Candidates to be returned from Reservation"]
    return pd.DataFrame([dict(zip(cols, r, strict=True)) for r in rows])


def _counts(rows):
    cols = ["Election Program Name", "LocalBody Name", "Division", "District", "Taluka", "Name of Contesting Candidate",
            "Candidate Gender", "Candidate Cast", "Ward No.", "Ward Reservation", "Total Votes Secured", "SymbolName", "Rank"]
    return pd.DataFrame([dict(zip(cols, r, strict=True)) for r in rows])


def test_sarpanch_seat_printed_under_a_ward_number():
    from local_elections_maharashtra.collect.admit import NamedSarpanchWards, sarpanch_rows

    p = "Second Phase G P Sarpanch General Election 16-10-2017"
    seats = _seats([
        [p, "Alur", "Osmanabad", "Umarga", "1", "SARPANCH PRABHAG", "B.C.C.", "900", "800", "0", ""],   # sarpanch seat, ward 1
        [p, "Tekoli", "Kolhapur", "Shahuwadi", "999", "SARPANCH", "GEN", "300", "280", "0", ""],         # ordinary ward-999 seat
        [p, "Tekoli", "Kolhapur", "Shahuwadi", "1", "SARPANCH PRABHAG", "GEN", "300", "280", "0", ""],   # repeats the 999 seat
        [p, "Nile", "Kolhapur", "Shahuwadi", "2", "WARD NO 2", "GEN(W)", "200", "190", "0", "1"],        # a member seat
        [p, "Loni", "Aurangabad", "Khultabad", "1", "SARPANCH", "GEN", "200", "190", "0", ""],           # two wards named for
        [p, "Loni", "Aurangabad", "Khultabad", "2", "SARPANCH", "GEN(W)", "210", "180", "0", ""],        # the sarpanch: neither
    ])
    counts = _counts([
        [p, "Alur", "Aurangabad", "Osmanabad", "Umarga", "NOTA", "", "", "1", "B.C.C.", "1551", "", "1"],    # Alur's contest: kept
        [p, "Alur", "Aurangabad", "Osmanabad", "Umarga", "NOTA", "", "", "1", "GEN", "40", "", "2"],         # other reservation: withheld
        [p, "Nile", "Kolhapur", "Kolhapur", "Shahuwadi", "NOTA", "", "", "2", "GEN(W)", "120", "", "1"],     # member contest: withheld
        [p, "Alur", "Aurangabad", "Osmanabad", "Umarga", "NOTA", "", "", "1", "", "10", "", "3"],            # no reservation printed: withheld
    ])
    named = NamedSarpanchWards([seats, counts])
    keep_seats, seats_999, _ = sarpanch_rows(seats, "ward_seat", named)
    assert keep_seats.tolist() == [True, True, False, False, False, False]
    assert seats_999.tolist() == [False, True, False, False, False, False]
    keep_counts, counts_999, _ = sarpanch_rows(counts, "counting", named)
    assert keep_counts.tolist() == [True, False, False, False]
    assert not counts_999.any()


def _counting(rows):
    columns = ["Election Program Name", "District", "Taluka", "LocalBody Name", "Name of Contesting Candidate",
               "Candidate Gender", "Candidate Cast", "Ward No.", "Ward Reservation", "Total Votes Secured", "SymbolName",
               "Rank"]
    return pd.DataFrame([["P 2018", "Nagpur", "Kuhi", *r] for r in rows], columns=columns)


def test_a_seat_alias_stands_only_on_the_same_rows_under_the_other_spelling():
    from collections import Counter

    from local_elections_maharashtra.build.checks import alias_evidence

    old = _counting([["Tekadi", "A", "Female", "GEN", "999", "GEN(W)", "200", "Bat", "1"],
                     ["Tekadi", "B", "Female", "GEN", "999", "GEN(W)", "190", "Cup", "2"],
                     ["Babul", "C", "Male", "SC", "999", "S.C.", "300", "Kite", "1"],
                     ["Chikana", "D", "Male", "SC", "999", "S.C.", "250", "Fan", "1"]])
    new = _counting([["Tekadi Van", "A", "Female", "GEN", "999", "GEN(W)", "200", "Bat", "1"],
                     ["Tekadi Van", "B", "Female", "GEN", "999", "GEN(W)", "190", "Cup", "2"],
                     ["Babul", "C", "Male", "SC", "999", "S.C.", "300", "Kite", "1"],
                     ["Chikana", "D", "Male", "SC", "999", "S.C.", "250", "Fan", "1"]])
    counting = {"old.csv": old, "new.csv": new}
    key = "p2018|nagpur|kuhi|{}".format
    seats = Counter([key("tekadivan"), key("babul"), key("chikana")])
    released = {key("tekadi"): {"old.csv"}, key("babul"): {"old.csv"}, key("chikana"): {"old.csv"}}
    assert alias_evidence({key("tekadi"): key("tekadivan")}, counting, seats, released) == []
    # two different GPs that both downloads print: never backed
    assert alias_evidence({key("babul"): key("chikana")}, counting, seats, released)
    # an alias to a spelling that is not a Ward-Seat seat
    assert alias_evidence({key("tekadi"): key("tekadix")}, counting, seats, released)
    # the other download prints the spelling with other votes
    changed = new.copy()
    changed.loc[0, "Total Votes Secured"] = "201"
    assert alias_evidence({key("tekadi"): key("tekadivan")}, {"old.csv": old, "new.csv": changed}, seats, released)


def test_admit_never_replaces_a_file_with_other_bytes(tmp_path, monkeypatch):
    import pytest

    from local_elections_maharashtra.collect import admit

    monkeypatch.setattr(admit, "ROOT", tmp_path)
    target = tmp_path / "data" / "raw" / "sec" / "counting" / "Counting_Report_03_06_2023 (10).xls"
    admit.write_once(target, b"first download", "first")
    admit.write_once(target, b"first download", "a rerun")  # the same bytes again: allowed
    with pytest.raises(SystemExit):
        admit.write_once(target, b"another download, same name", "second")
    assert target.read_bytes() == b"first download"
