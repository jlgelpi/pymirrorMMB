#!/usr/bin/env python3
#encoding: UTF-8

"""Updates checking data from new cif files."""

import argparse
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from contextlib import redirect_stdout
from io import StringIO
import logging
import multiprocessing
import os
import shutil
import sys
import tempfile
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

def fetch_structure_cif(pdb_id, api_prefix, cif_gfs=None, ass_gfs=None, output_dir=TMPDIR):
    if cif_gfs is not None:
        # Fetch from GridFS
        if '_' in pdb_id:
            # It's an assembly
            fn = f"{pdb_id.replace('_','-assembly')}.cif.gz"
            grid_out = ass_gfs.open_download_stream_by_name(fn)
        else:
            fn = f"{pdb_id.lower()}.cif.gz"
            grid_out = cif_gfs.open_download_stream_by_name(fn)
        cif_data = grid_out.read()
        cif_path = os.path.join(output_dir, fn)
        with open(cif_path, "wb") as cif_file:
            cif_file.write(cif_data)

    else:
        cif_url = f"{api_prefix}/{pdb_id}.cif"
        logging.info(f"Fetching CIF file from {cif_url}")
        with urlopen(cif_url) as response:
            if response.status != 200:
                raise ValueError(f"Unexpected HTTP status: {response.status}")
            cif_data = response.read()
        cif_path = os.path.join(output_dir, f"{pdb_id}.cif")

    with open(cif_path, "wb") as cif_file:
        cif_file.write(cif_data)
    return cif_path

def check_structure(base_dir_path, atom_limit, cache_dir, str_file):
    settings = cts.set_defaults(base_dir_path=base_dir_path)
    settings['no_network'] = False
    settings['nocache'] = True
    settings['check_only'] = True
    settings['non_interactive'] = True
    settings['cache_dir'] = cache_dir
    settings['limit'] = atom_limit
    settings['input_structure_path'] = str_file

    output = StringIO()
    with redirect_stdout(output):
        checker = StructureChecking(base_dir_path, settings)
        checker.checkall()
    checker.summary['report'] = output.getvalue()
    return checker.summary

def cleanup_temp_dir(pdb_id, tmp_dir):
    try:
        shutil.rmtree(tmp_dir)
    except OSError as e:
        logging.error(f"Error removing temporary files for code {pdb_id}: {e}")

def update_checking_data(
        args, 
        codes, 
        chk_col, 
        cif_gfs=None, 
        ass_gfs=None
    ):
    """Update checking data for the given codes."""
    base_dir_path = biobb_structure_checking.__path__[0]
    codes = list(codes)
    if args.workers < 1:
        raise ValueError("workers must be at least 1")
    workers = min(args.workers, len(codes)) if codes else 1

    with ThreadPoolExecutor(max_workers=workers) as fetch_pool, \
            ProcessPoolExecutor(
                max_workers=workers,
                mp_context=multiprocessing.get_context("spawn")
            ) as check_pool:
        fetch_futures = {}
        check_futures = {}
        ready_checks = deque()
        next_code = 0

        while next_code < len(codes) or fetch_futures or check_futures or ready_checks:
            while ready_checks and len(check_futures) < workers:
                pdb_id, tmp_dir, str_file = ready_checks.popleft()
                try:
                    future = check_pool.submit(
                        check_structure,
                        base_dir_path,
                        args.atom_limit,
                        tmp_dir,
                        str_file
                    )
                    check_futures[future] = (pdb_id, tmp_dir)
                except Exception as e:
                    logging.error(f"Error scheduling structure check for code {pdb_id}: {e}")
                    cleanup_temp_dir(pdb_id, tmp_dir)

            while (
                next_code < len(codes)
                and len(fetch_futures) < workers
                and len(check_futures) + len(ready_checks) < 2 * workers
            ):
                index = next_code
                pdb_id = codes[index]
                next_code += 1
                logging.info(f"Processing code: {pdb_id}")
                tmp_dir = tempfile.mkdtemp(prefix=f"pdb-{pdb_id}-", dir=TMPDIR)
                try:
                    future = fetch_pool.submit(
                        fetch_structure_cif,
                        pdb_id,
                        args.api_prefix,
                        cif_gfs=cif_gfs,
                        ass_gfs=ass_gfs,
                        output_dir=tmp_dir
                    )
                    fetch_futures[future] = (pdb_id, tmp_dir)
                except Exception as e:
                    logging.error(f"Error scheduling CIF fetch for code {pdb_id}: {e}")
                    cleanup_temp_dir(pdb_id, tmp_dir)

            pending = set(fetch_futures) | set(check_futures)
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)

            for future in completed:
                if future in fetch_futures:
                    pdb_id, tmp_dir = fetch_futures.pop(future)
                    try:
                        str_file = future.result()
                        ready_checks.append((pdb_id, tmp_dir, str_file))
                    except Exception as e:
                        logging.error(f"Error fetching CIF file for code {pdb_id}: {e}")
                        cleanup_temp_dir(pdb_id, tmp_dir)
                    continue

                pdb_id, tmp_dir = check_futures.pop(future)
                try:
                    summary = future.result()
                except SystemExit as e:
                    logging.error(f"Structure checking failed for code {pdb_id}: {e}")
                except Exception as e:
                    logging.error(f"Error checking structure for code {pdb_id}: {e}")
                else:
                    try:
                        chk_col.update_one(
                            {'_id': pdb_id},
                            {'$set': summary},
                            upsert=True
                        )
                        logging.info(f"Updated checking data for code {pdb_id}")
                    except Exception as e:
                        logging.error(f"Error updating checking data for code {pdb_id}: {e}")
                finally:
                    cleanup_temp_dir(pdb_id, tmp_dir)

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
        "--workers",
        type=int,
        help="Maximum number of CIF downloads and structure checks to run concurrently.",
        default=2
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
    if args.workers < 1:
        cmd.error("--workers must be at least 1")

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
