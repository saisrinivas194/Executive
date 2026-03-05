#!/usr/bin/env python3
"""
Read exec donation data from spreadsheets, sum by company and year (rep/dem),
and upload to Firestore.

Writes under: companies/<company_id>/records/<year> with exec.rep and exec.dem
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process
import firebase_admin
from firebase_admin import credentials, firestore


def load_config(config_path):
    with open(config_path) as f:
        return json.load(f)


def load_contributor_to_company_map(csv_path):
    """Build map: contributor name -> company name. First row per contributor wins."""
    path = Path(csv_path)
    if not path.exists():
        return {}
    table = pd.read_csv(path)
    if "contributor_name" not in table.columns or "company_name" not in table.columns:
        return {}
    result = {}
    for _, row in table.iterrows():
        contributor = str(row["contributor_name"]).strip().upper()
        company = str(row["company_name"]).strip()
        if contributor and contributor not in result:
            result[contributor] = company
    return result


def read_sheet(file_path, sheet_name_or_index, column_map, contributor_to_company=None, default_year=None):
    """Load spreadsheet and normalize columns. Resolve contributors to companies if needed."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    ext = path.suffix.lower()
    if ext in (".xlsx", ".xlsm"):
        sheet = pd.read_excel(path, sheet_name=sheet_name_or_index or 0, engine="openpyxl")
    elif ext == ".xls":
        sheet = pd.read_excel(path, sheet_name=sheet_name_or_index or 0)
    else:
        sheet = pd.read_csv(path, encoding="utf-8", encoding_errors="replace")

    # Rename columns to our internal names (spreadsheet header -> our name)
    header_to_internal = {v: k for k, v in column_map.items()}
    sheet = sheet.rename(columns=header_to_internal)

    has_company = "company_name" in sheet.columns
    has_contributor = "contributor_name" in sheet.columns
    if not has_company and not (has_contributor and contributor_to_company):
        raise ValueError(
            "Sheet must have company name or contributor name (and crosswalk). "
            f"Columns after mapping: {list(sheet.columns)}"
        )

    year_used = default_year if default_year is not None else 2024
    if "election_year" not in sheet.columns:
        sheet["election_year"] = str(year_used)
    if "rep_amount" not in sheet.columns:
        sheet["rep_amount"] = 0
    if "dem_amount" not in sheet.columns:
        sheet["dem_amount"] = 0

    if has_contributor and contributor_to_company and not has_company:
        def lookup(contributor):
            key = str(contributor).strip().upper()
            return contributor_to_company.get(key, "")

        sheet["company_name"] = sheet["contributor_name"].map(lookup)
        no_company = sheet["company_name"] == ""
        dropped = no_company.sum()
        if dropped:
            sheet = sheet[~no_company].copy()
            print(f"Crosswalk: dropped {dropped} rows with no company.")

    return sheet


def parse_money(series):
    """Turn values like $1,234.56 into numbers."""
    return pd.to_numeric(
        series.astype(str).str.replace(r"[$,\s]", "", regex=True),
        errors="coerce",
    ).fillna(0)


def sum_by_company_and_year(sheet):
    """Group by company and election year, sum rep and dem amounts."""
    sheet = sheet.copy()
    sheet["rep_amount"] = parse_money(sheet["rep_amount"])
    sheet["dem_amount"] = parse_money(sheet["dem_amount"])
    sheet["election_year"] = sheet["election_year"].astype(str).str.strip()
    sheet = sheet[sheet["election_year"].str.match(r"^\d{4}$", na=False)]

    grouped = sheet.groupby(["company_name", "election_year"], as_index=False).agg(
        rep=("rep_amount", "sum"),
        dem=("dem_amount", "sum"),
    )
    return grouped


def fetch_companies_from_firestore(db, collection_name, name_field, id_field=None):
    """Return list of (company_id, company_name) for every doc in the collection."""
    coll = db.collection(collection_name)
    pairs = []
    for doc in coll.stream():
        doc_id = doc.id
        data = doc.to_dict()
        name = data.get(name_field) or data.get("name") or ""
        if not isinstance(name, str):
            name = str(name)
        company_id = (data.get(id_field) if id_field else None) or doc_id
        pairs.append((company_id, name.strip()))
    return pairs


def find_best_company_match(name_from_sheet, firebase_company_list, min_score_0_to_1):
    """Return company_id if we find a Firebase company name close enough to name_from_sheet, else None."""
    firebase_names = [n for _, n in firebase_company_list]
    if not firebase_names:
        return None
    match = process.extractOne(
        name_from_sheet,
        firebase_names,
        scorer=fuzz.ratio,
        score_cutoff=int(min_score_0_to_1 * 100),
    )
    if match is None:
        return None
    _matched_name, _score, index = match
    return firebase_company_list[index][0]


def write_records_to_firestore(db, collection_name, rows, company_id_for_name, dry_run):
    """Write each row to companies/<id>/records/<year> with exec.rep and exec.dem. Returns (written, skipped)."""
    written = 0
    skipped = 0
    total_rows = len(rows)
    print(f"Uploading {total_rows} records...", flush=True)

    for i, (_, row) in enumerate(rows.iterrows(), start=1):
        company_name = str(row["company_name"]).strip()
        year = str(row["election_year"]).strip()
        rep = float(row["rep"])
        dem = float(row["dem"])

        company_id = company_id_for_name.get(company_name)
        if not company_id:
            skipped += 1
            continue

        record_ref = (
            db.collection(collection_name)
            .document(company_id)
            .collection("records")
            .document(year)
        )
        payload = {"exec": {"rep": rep, "dem": dem}}
        if not dry_run:
            record_ref.set(payload, merge=True)
        written += 1
        if i % 100 == 0 or i == total_rows:
            print(f"  {i}/{total_rows} done", flush=True)

    return written, skipped


def main():
    parser = argparse.ArgumentParser(description="Upload exec data from spreadsheet to Firebase")
    parser.add_argument("config", nargs="?", default="config.json", help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Do not write to Firebase")
    args = parser.parse_args()

    config_file = Path(args.config)
    if not config_file.exists():
        print(f"Config not found: {config_file}", file=sys.stderr)
        print("Copy config.example.json to config.json and fill in paths.", file=sys.stderr)
        return 1

    config = load_config(config_file)
    dry_run = args.dry_run or config.get("dry_run", False)
    if dry_run:
        print("DRY RUN: no writes to Firebase.")

    # Load contributor -> company map if configured
    contributor_to_company = {}
    crosswalk_path = config.get("contributor_crosswalk_path")
    if crosswalk_path and Path(crosswalk_path).exists():
        contributor_to_company = load_contributor_to_company_map(crosswalk_path)
        print(f"Loaded {len(contributor_to_company)} contributor->company mappings.")
    elif crosswalk_path:
        print(f"Warning: crosswalk file not found: {crosswalk_path}", file=sys.stderr)

    # Read and aggregate spreadsheet
    column_map = config["column_mapping"]
    sheet = read_sheet(
        config["spreadsheet_path"],
        config.get("spreadsheet_sheet"),
        column_map,
        contributor_to_company=contributor_to_company or None,
        default_year=config.get("default_election_year"),
    )
    rows = sum_by_company_and_year(sheet)
    print(f"Aggregated {len(rows)} rows (company x year).")

    # If sheet had no data, use unique companies from crosswalk with default year and 0/0
    if len(rows) == 0 and contributor_to_company:
        default_year = str(config.get("default_election_year") or 2024)
        invalid = {"", "0", "nan"}
        company_names = sorted(
            c for c in set(contributor_to_company.values())
            if c and str(c).strip() and str(c).strip().lower() not in invalid
        )
        if company_names:
            rows = pd.DataFrame({
                "company_name": company_names,
                "election_year": default_year,
                "rep": 0.0,
                "dem": 0.0,
            })
            print(f"Sheet empty; using {len(rows)} companies from crosswalk (year={default_year}, rep=0, dem=0).")

    # Connect to Firebase
    cred_path = config["firebase"]["credentials_path"]
    if not Path(cred_path).exists():
        print(f"Credentials file not found: {cred_path}", file=sys.stderr)
        return 1

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    collection_name = config["firebase"]["companies_collection"]
    name_field = config["firebase"]["company_name_field"]
    id_field = config["firebase"].get("company_id_field")

    firebase_company_list = fetch_companies_from_firestore(db, collection_name, name_field, id_field)
    print(f"Loaded {len(firebase_company_list)} companies from Firebase.")

    # Match sheet company names to Firebase company ids
    match_threshold = config.get("fuzzy_match_threshold", 0.75)
    company_id_for_name = {}
    unmatched_names = []
    for name in rows["company_name"].astype(str).str.strip().unique():
        company_id = find_best_company_match(name, firebase_company_list, match_threshold)
        if company_id is not None:
            company_id_for_name[name] = company_id
        else:
            unmatched_names.append(name)

    if unmatched_names:
        print(f"Unmatched (no Firebase company above {match_threshold}): {len(unmatched_names)}")
        for n in unmatched_names[:20]:
            print(f"  - {n}")
        if len(unmatched_names) > 20:
            print(f"  ... and {len(unmatched_names) - 20} more.")

    written, skipped = write_records_to_firestore(
        db, collection_name, rows, company_id_for_name, dry_run
    )
    print(f"Written: {written}, Skipped: {skipped}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
