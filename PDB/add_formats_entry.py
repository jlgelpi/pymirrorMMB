#!/usr/bin/env python3
#encoding: UTF-8
"""Annotate PDB entry documents with available file formats."""

import argparse
import logging
import os
import sys

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite

DATA_GFS = 'PDB_DataFiles.files'
ASSEMBLIES_GFS = 'PDB_Assemblies.files'
ENTRIES_COL = 'PDB_Entry'
BATCH_SIZE = 10000

AUTH = True

def main():
    """Parse arguments and sync files to GridFS."""
    cmd = argparse.ArgumentParser(
        description="Annotate PDB entry documents with available file formats"
    )
    cmd.add_argument("--host", default="localhost", help="MongoDB host (default: localhost)")
    cmd.add_argument("--database", default="FlexPortal", help="MongoDB database (default: FlexPortal)")
    cmd.add_argument("--debug", action="store_true", help="Debug logging")
    args = cmd.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d|%H:%M:%S",
    )
    logging.getLogger().setLevel(10 if args.debug else 20)

    db_lnk = MongoDB(args.host, args.database, False, AUTH)
    db_lnk.connect_db()

    cols = db_lnk.get_collections([ENTRIES_COL, DATA_GFS])
    entries_col = cols[ENTRIES_COL]
    datafiles_col = cols[DATA_GFS]
    bulk = MongoDBBulkWrite(entries_col, CTS["UPSERT"], BATCH_SIZE)

    #assemblies_files_col = db_lnk.get_collection(ASSEMBLIES_GFS, True)

    logging.info("Updating entry documents with available file formats...")
    logging.info("Clearing existing formats annotations...")
    entries_col.update_many({}, {"$unset": {"formats": 1}})
    logging.info("Fetching available files from GridFS...")
    file_formats = []
    for file_doc in datafiles_col.find({}, {"filename": 1}):
        filename = file_doc["filename"]
        file_format = ''
        if filename.startswith("pdb") and filename.endswith(".ent.gz"):
            entry_id = filename[3:7].upper()
            file_format = "pdb"
        elif filename.endswith(".cif.gz"):
            entry_id = filename[:4].upper()
            file_format = "mmCif"
        bulk.append(
            {"_id": entry_id},
            {"$addToSet": {"formats": file_format}}
        )
        bulk.commit_data_if_full()
    bulk.commit_any_data()
    logging.info("Done.")

if __name__ == "__main__":
    raise SystemExit(main())
