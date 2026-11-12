#!/usr/bin/env python3
#encoding: UTF-8

"""Updates checking data from new cif files."""

import argparse
import logging
import os
import sys

from mmb_data.mongo_db_connect import MongoDB

from biobb_structure_checking.constants import help, set_defaults
from biobb_structure_checking.structure_checking import StructureChecking

AUTH = True

BUCKETS = {
    "assemblies" : "PDB_Assemblies",
    "structures" : "PDB_DataFiles",
}

CHECKING_COL = "PDB_Checking"
ENTRIES_COL = "PDB_Entry"
ASSEMBLIES_COL = "PDB_Assemblies.files"

def fetch_codes(col, query={}):
    return list(col.find(query, projection={'_id':1}))

def fetch_assemblies_codes(pdb_codes, ass_col):
    files = set(fetch_codes(ass_col, query={'filename': '/cif/'}))
    print(f"Fetched {len(files)} assembly files from {ASSEMBLIES_COL}")
        


def main():
    """Parse arguments and sync files to GridFS."""
    cmd = argparse.ArgumentParser(
        description="Update chgecking data from new cif files"
    )
    cmd.add_argument(
        "-d", "--debug", action="store_true", default=False
    )
    cmd.add_argument(
        "-c",
        "--command",
        type=str,
        help="Command to execute: default checkall",
        default="checkall"
    )
    cmd.add_argument(
        "--atom_limit",
        action="store",
        type=int,
        help="Max number of atoms to include in the update (default: 1000000).",
        default=1000000
    )
    cmd.add_argument(
        "--which", 
        action="store", 
        type=str, 
        help="Which cif files to process: assemblies or structures (default:both)", 
        default="both", 
        choices=['assemblies', 'structures', 'both']
    )
    cmd.add_argument("--host", default="localhost", help="MongoDB host (default: localhost)")
    cmd.add_argument("--database", default="FlexPortal", help="MongoDB database (default: FlexPortal)")
    
    args = cmd.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d|%H:%M:%S",
    )
    logging.getLogger().setLevel(10 if args.debug else 20)

    # Connect to MongoDB
    logging.info(f"Connecting to MongoDB database {args.database} at {args.host}")
    db_lnk = MongoDB(args.host, args.database, False, AUTH)
    db_lnk.connect_db()
    
    ass_bucket = db_lnk.get_gfs(BUCKETS['assemblies'])
    cif_bucket = db_lnk.get_gfs(BUCKETS['structures'])
    
    cols = db_lnk.get_collections([CHECKING_COL, ENTRIES_COL, ASSEMBLIES_COL])
    chk_col = cols[CHECKING_COL]
    ent_col = cols[ENTRIES_COL]
    ass_col = cols[ASSEMBLIES_COL]
       
    chk_codes = fetch_codes(chk_col)
    logging.info(f"Fetched {len(chk_codes)} from {CHECKING_COL}")
    
    pdb_codes = fetch_codes(ent_col)
    logging.info(f"Fetched {len(pdb_codes)} from {ENTRIES_COL}")
    
    ass_codes = []

    if args.which in ["assemblies", "both"]:
        ass_codes = fetch_assembly_codes(pdb_codes, ass_col)
        logging.info(f"Fetched {len(ass_codes)} from assemblies")
    if args.which == 'assemblies':
        to_do = ass_codes
    elif args.which == 'structures':
        to_do = pdb_codes
    else:
        to_do = set(pdb_codes) + set(ass_codes)
    
        
        
    
if __name__ == "__main__":
    main()
