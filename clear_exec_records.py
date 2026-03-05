#!/usr/bin/env python3
"""
Delete all records under each company (the exec data we uploaded).
Company docs stay; only the records subcollection is cleared.
"""

import argparse
import json
import sys
from pathlib import Path

import firebase_admin
from firebase_admin import credentials, firestore


def load_config(config_path):
    with open(config_path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="Clear exec records from all companies")
    parser.add_argument("config", nargs="?", default="config.json", help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Only show what would be deleted")
    args = parser.parse_args()

    config_file = Path(args.config)
    if not config_file.exists():
        print(f"Config not found: {config_file}", file=sys.stderr)
        return 1

    config = load_config(config_file)
    cred_path = config["firebase"]["credentials_path"]
    if not Path(cred_path).exists():
        print(f"Credentials not found: {cred_path}", file=sys.stderr)
        return 1

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()

    collection_name = config["firebase"]["companies_collection"]
    coll = db.collection(collection_name)

    if args.dry_run:
        print("DRY RUN: would delete records under each company.")
    else:
        print("Deleting records...", flush=True)

    records_deleted = 0
    companies_with_records = 0
    company_docs = list(coll.stream())

    for company_doc in company_docs:
        company_id = company_doc.id
        records_coll = coll.document(company_id).collection("records")
        record_docs = list(records_coll.stream())
        if not record_docs:
            continue
        companies_with_records += 1
        for rec in record_docs:
            if not args.dry_run:
                rec.reference.delete()
            records_deleted += 1
        if companies_with_records % 200 == 0 and not args.dry_run:
            print(f"  {companies_with_records} companies, {records_deleted} records cleared", flush=True)

    if args.dry_run:
        print(f"Would delete {records_deleted} records from {companies_with_records} companies.")
    else:
        print(f"Done. Deleted {records_deleted} records from {companies_with_records} companies.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
