#!/usr/bin/env python3
#encoding: UTF-8
"""Add structure sequence."""

import argparse
import logging
import os
import sys
import gzip
import io
import requests

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite

from biobb_structure_checking import structure_checking

DATA_GFS = 'PDB_DataFiles.files'
ENTRIES_COL = 'PDB_Entry'
SEQUENCES_COL = 'sequences'
BATCH_SIZE = 10000
PDBCHECK_COL = 'PDB_Checking'
APICHECK_PREFIX = 'https://mdb-login.bsc.es/api/pdbChecking/'

AUTH = True

def read_fasta(f):
    lines = f.split('\n')
    return lines[0], ''.join(lines[1:])


def main():
    """Parse arguments and sync files to GridFS."""
    cmd = argparse.ArgumentParser(
        description="Add structure sequence to PDB entry documents"
    )
    cmd.add_argument("--host", default="localhost", help="MongoDB host (default: localhost)")
    cmd.add_argument("--database", default="FlexPortal", help="MongoDB database (default: FlexPortal)")
    cmd.add_argument("--debug", action="store_true", help="Debug logging")
    cmd.add_argument("--bucket", default="PDB_DataFiles", help="GridFS bucket name (default: PDB_DataFiles)")
    args = cmd.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d|%H:%M:%S",
    )
    logging.getLogger().setLevel(10 if args.debug else 20)

    db_lnk = MongoDB(args.host, args.database, False, AUTH)
    db_lnk.connect_db()

    cols = db_lnk.get_collections([ENTRIES_COL, SEQUENCES_COL, PDBCHECK_COL])
    entries_col = cols[ENTRIES_COL]
    sequences_col = cols[SEQUENCES_COL]
    checking_col = cols[PDBCHECK_COL]

    bulk = MongoDBBulkWrite(sequences_col, CTS["UPDATE"], BATCH_SIZE)

    #assemblies_files_col = db_lnk.get_collection(ASSEMBLIES_GFS, True)
    codes = list(entries_col.find(
        {'supersby': {'$exists': False}},
        {'_id': 1})
    )
    total = len(codes)
    processed = 0
    logging.info(f"Found {total} entries")

    for code in codes:
        id_code = code['_id']
        processed += 1
        logging.info(f"Processing {id_code} ({processed}/{total})")
        if not id_code:
            continue
        id_code_lc = id_code.lower()
        try:
            fasta = checking_col.find_one({'_id':id_code})['FASTA']
            canonical = fasta['canonical']
            structure = fasta['structure']
        except:
            logging.warning(f"Not sequence data found for {id_code}, skipping")
            continue
        can_chains = canonical.split(">")[1:]
        pdb_chains = structure.split(">")[1:]
        for index,can_ch in chains.items():
            pdb_ch = pdb_chains[index]
            can_header,can_seq = read_fasta(can_ch)
            pdb_header,pdb_seq = read_fasta(pdb_ch)
            header_data = pdb_header.split(' ', 1)
            chain_id = f'{id_code}_{header_data[0].replace('pdb_sq_','')}'
            if '/' in chain_id:
                ch_id, model = chain_id.split('/')
                if model != '0':
                    continue
            else:
                ch_id = chain_id

            # TODO calc fragments
            logging.debug(f"Adding {ch_id}: {pdb_seq}")
            bulk.append(
                    {'_id' : ch_id},
                    {'$set': {'PDBSequence':pdb_seq}}
            )

            bulk.commit_data_if_full()
    bulk.commit_any_data()
    logging.info("Done.")

if __name__ == "__main__":
    raise SystemExit(main())
