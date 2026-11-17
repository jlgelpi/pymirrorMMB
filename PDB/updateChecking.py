#!/usr/bin/env python3
#encoding: UTF-8

"""Updates checking data from new cif files."""

import argparse
from contextlib import redirect_stdout
from io import StringIO
import logging
import os
import sys
from urllib.request import urlopen

from mmb_data.mongo_db_connect import MongoDB
import biobb_structure_checking
import biobb_structure_checking.constants as cts
from biobb_structure_checking.structure_checking import StructureChecking

AUTH = True
TMPDIR = "/tmp"
BUCKETS = {
    "assemblies" : "PDB_Assemblies",
    "structures" : "PDB_DataFiles",
}

CHECKING_COL = "PDB_Checking"
ENTRIES_COL = "PDB_Entry"
API_PREFIX = "https://mdb-login.bsc.es/api/pdb"


def fetch_codes(col, query={}, projection={'_id':1}):
    return list(col.find(query, projection=projection))

def get_assemblies_codes(pdb_entries):
    ass_codes = []
    for code in pdb_entries:
        if code.get('assemblies'):
            ass_codes.extend(code['assemblies'])
    return [code.replace('-assembly', '_').upper() for code in ass_codes]

def fetch_structure_cif(pdb_id, api_prefix, cif_gfs=None, ass_gfs=None):
    if cif_gfs is not None:
        # Fetch from GridFS
        if '_' in pdb_id:
            # It's an assembly
            fn = f"{pdb_id.replace('_','-assembly')}.cif.gz"
            grid_out = ass_gfs.get_last_version(fn)
        else:
            fn = f"{pdb_id.lower()}.cif.gz"
            grid_out = cif_gfs.get_last_version(fn)
        cif_data = grid_out.read()
        cif_path = os.path.join(TMPDIR, fn)
        with open(cif_path, "wb") as cif_file:
            cif_file.write(cif_data)

    else:
        cif_url = f"{api_prefix}/{pdb_id}.cif"
        logging.info(f"Fetching CIF file from {cif_url}")
        with urlopen(cif_url) as response:
            if response.status != 200:
                raise ValueError(f"Unexpected HTTP status: {response.status}")
            cif_data = response.read()
        cif_path = os.path.join(TMPDIR, f"{pdb_id}.cif")

    with open(cif_path, "wb") as cif_file:
        cif_file.write(cif_data)
    return cif_path

def update_checking_data(
        args, 
        codes, 
        chk_col, 
        cif_gfs=None, 
        ass_gfs=None
    ):
    """Update checking data for the given codes."""
    settings = cts.set_defaults(base_dir_path)
    settings['no_network']=False
    settings['nocache']=True
    settings['check_only']=True
    settings['non_interactive']=True
    settings['cache_dir']=TMPDIR
    settings['limit']=args.atom_limit
    base_path = TMPDIR

    for pdb_id in codes:
        logging.info(f"Processing code: {pdb_id}")
        try:
            # Fetch the cif file from the API
            base_path = TMPDIR
            str_file = fetch_structure_cif(pdb_id, args.api_prefix, cif_gfs=cif_gfs, ass_gfs=ass_gfs)
            settings['input_structure_path'] = str_file
          
            # Perform structure checking
            try:
                output = StringIO()
                with redirect_stdout(output):
                    checker = StructureChecking(base_path, settings)
                    checker.checkall()
                checker.summary['report'] = output.getvalue()
            except Exception as e:
                logging.error(f"Error checking structure for code {pdb_id}: {e}")
                continue
            try:
                chk_col.update_one({'_id': pdb_id}, {'$set': checker.summary}, upsert=True)
                logging.info(f"Updated checking data for code {pdb_id}")
            except Exception as e:
                logging.error(f"Error updating checking data for code {pdb_id}: {e}")
                continue
        except Exception as e:
            logging.error(f"Error processing code {pdb_id}: {e}")
            continue


def main():
    """Parse arguments and sync files to GridFS."""
    cmd = argparse.ArgumentParser(
        description="Update chgecking data from new cif files"
    )
    cmd.add_argument(
        "-d", "--debug", action="store_true", default=False
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
    cmd.add_argument(
        "--force", 
        action="store_true", 
        help="Force update of checking data even if it already exists (default: False)", 
        default=False
    )
    cmd.add_argument(
        "--api_prefix", 
        action="store", 
        type=str, 
        help="API prefix for fetching cif files (default: https://mdb-login.bsc.es/api/pdb)", 
        default=API_PREFIX
    )
    cmd.add_argument("--host", default="localhost", help="MongoDB host (default: localhost)")
    cmd.add_argument("--database", default="FlexPortal", help="MongoDB database (default: FlexPortal)")
    cmd.add_argument("--use_gfs", action="store_true", help="Use GridFS for retrieving files")
    args = cmd.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d|%H:%M:%S",
    )
    logging.getLogger().setLevel(10 if args.debug else 20)

    # Connect to MongoDB
    try:
        logging.info(f"Connecting to MongoDB database {args.database} at {args.host}")
        db_lnk = MongoDB(args.host, args.database, False, AUTH)
        db_lnk.connect_db()
        cols = db_lnk.get_collections([CHECKING_COL, ENTRIES_COL])
        chk_col = cols[CHECKING_COL]
        ent_col = cols[ENTRIES_COL]
        cif_gfs = None
        ass_gfs = None
        if args.use_gfs:
            logging.info("Using GridFS for file retrieval")
            cif_gfs = db_lnk.get_gfs(BUCKETS['structures'])
            ass_gfs = db_lnk.get_gfs(BUCKETS['assemblies'])

    except Exception as e:
        logging.error(f"Error connecting to MongoDB: {e}")
        sys.exit(1)

    try:
        logging.info(f"Fetching codes from {CHECKING_COL} and {ENTRIES_COL}")
        
        chk_codes = set(code['_id'].upper() for code in fetch_codes(chk_col))
        logging.info(f"Fetched {len(chk_codes)} codes from {CHECKING_COL}")
        
        pdb_entries = fetch_codes(
            ent_col, 
            query={'supersby':{'$exists' : 0}},
            projection={'assemblies':1, '_id':1}
        )
        pdb_codes = [code['_id'].upper() for code in pdb_entries]

        
        logging.info(f"Fetched {len(pdb_codes)} codes from {ENTRIES_COL}")
    except Exception as e:
        logging.error(f"Error fetching codes: {e}")
        sys.exit(1)
    
    if args.which in ["assemblies", "both"]:
        ass_codes = get_assemblies_codes(pdb_entries)
        logging.info(f"Fetched {len(ass_codes)} assemblies")

    if args.which == 'assemblies':
        to_do = ass_codes
    elif args.which == 'structures':
        to_do = pdb_codes
    else:
        to_do = list(pdb_codes) + list(ass_codes)

    if not args.force:
        to_do_filtered = [code for code in to_do if code not in chk_codes]
        logging.info(f"Filtered {len(to_do_filtered)} codes to process (excluding already checked codes)")
        print(to_do_filtered[0:10])
    else:
        to_do_filtered = to_do
        logging.info(f"Force update enabled, processing all {len(to_do)} codes")
    
        logging.info(f"Processing {len(to_do_filtered)} total codes")

    logging.info(f"Initializing checking process...")

    update_checking_data(args, to_do_filtered, chk_col, cif_gfs=cif_gfs, ass_gfs=ass_gfs)
    
    
if __name__ == "__main__":
    main()
