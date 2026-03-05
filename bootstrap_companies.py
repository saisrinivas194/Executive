#!/usr/bin/env python3
"""
Create company docs in Firestore from the crosswalk CSV (one doc per company name).
Run once so the exec uploader has something to match against.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore


def load_config(config_path):
    with open(config_path) as f:
        return json.load(f)


def company_name_to_doc_id(company_name):
    """Same company name always gets the same id. Safe for Firestore doc ids."""
    normalized = company_name.strip().lower() or "unknown"
    digest = hashlib.sha256(normalized.encode("utf-8")).digest()[:12]
    return digest.hex()


def get_company_names_from_crosswalk(csv_path):
    """Unique company names from the CSV. Drops empty and invalid."""
    path = Path(csv_path)
    if not path.exists():
        return []
    table = pd.read_csv(path)
    if "company_name" not in table.columns:
        return []
    names = (
        table["company_name"]
        .astype(str)
        .str.strip()
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    skip = {"0", "nan"}
    return sorted(n for n in names if n and n.lower() not in skip)


def main():
    parser = argparse.ArgumentParser(description="Create company docs in Firebase from crosswalk CSV")
    parser.add_argument("config", nargs="?", default="config.json", help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Print what would be created, do not write")
    args = parser.parse_args()

    config_file = Path(args.config)
    if not config_file.exists():
        print(f"Config not found: {config_file}", file=sys.stderr)
        return 1

    config = load_config(config_file)
    crosswalk_path = config.get("contributor_crosswalk_path")
    if not crosswalk_path or not Path(crosswalk_path).exists():
        print(f"Crosswalk not found: {crosswalk_path}", file=sys.stderr)
        return 1

    company_names = get_company_names_from_crosswalk(crosswalk_path)
    print(f"Found {len(company_names)} companies in crosswalk.")

    if not company_names:
        print("Nothing to do.", file=sys.stderr)
        return 0

    cred_path = config["firebase"]["credentials_path"]
    if not Path(cred_path).exists():
        print(f"Credentials not found: {cred_path}", file=sys.stderr)
        return 1

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    collection_name = config["firebase"]["companies_collection"]
    name_field = config["firebase"]["company_name_field"]
    coll = db.collection(collection_name)

    if args.dry_run:
        print("DRY RUN: would create these company docs:")
        for name in company_names[:25]:
            print(f"  {company_name_to_doc_id(name)} -> {name!r}")
        if len(company_names) > 25:
            print(f"  ... and {len(company_names) - 25} more.")
        return 0

    count = 0
    for name in company_names:
        doc_id = company_name_to_doc_id(name)
        ref = coll.document(doc_id)
        ref.set({name_field: name}, merge=True)
        count += 1

    print(f"Done. Wrote {count} company docs to {collection_name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
