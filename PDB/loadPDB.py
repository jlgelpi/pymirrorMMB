#!/usr/bin/env python3
#encoding: UTF-8

"""Load PDB mirror data into MongoDB collections."""

import argparse
import gzip
import gridfs
import io
import logging
import os
import re
import sys
from datetime import datetime, timezone

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite

AUTH = True
BATCH_SIZE = 50000

DEFAULT_MIRROR = "/data/dbmirror"
DEFAULT_DATADIR = "/home/ubuntu/mirrorMMB/data"
AVAILABLE_CLUSTERS = ["30", "40", "50", "90", "95", "100"]

PATHS = {}  # Will be populated in main()

def print_log(msg):
    """Write a timestamped log message."""
    logging.info(msg)


def open_text_file(path):
    """Open a text file that may be gzip-compressed."""
    if path.endswith(".gz"):
        return gzip.open(path, "rt")
    return open(path, "r", encoding="utf-8")


def get_pdb_file(id):
    """Open a PDB entry file by id and return (handle, proc)."""
    if re.match(r"^[1-9]...$", id):
        fn = f"{PATHS['PREFIX']}/{id[1:3]}/pdb{id}.ent.gz"
    else:
        logging.error(f"id {id} does not match expected pattern")
        return None
    return fn


def close_cond(fh, proc):
    """Close a file handle and wait for the optional process."""
    fh.close()
    if proc:
        proc.wait()


def calc_mw(form, weights):
    """Calculate molecular weight and charge from a formula string."""
    mw = 0.0
    car = 0.0

    for tok in form.split()[1:]:
        if "+" in tok or "-" in tok:
            sign = 1 if "+" in tok else -1
            num = re.sub(r"[+-]", "", tok)
            num_val = int(num) if num else 1
            car = sign * num_val
        else:
            match = re.match(r"([A-Za-z]*)([0-9]*)", tok)
            if not match:
                continue
            el, num = match.groups()
            el = el.lower()
            num_val = int(num) if num else 1
            if el not in weights:
                print_log(f"Element -{el}- not found ({form})")
            else:
                mw += weights[el] * num_val
    return mw, car


def load_cluster_bc(cl, chains_col):
    """Load blast clusters (bc-*) into chain documents."""
    file_path = os.path.join(PATHS["CLUSTERS_DIR"], f"clusters-by-entity-{cl}.txt")
    logging.info(f"Loading cluster file {file_path}")
    cl_id = f"bc-{cl}"
    bulk = MongoDBBulkWrite(chains_col, CTS["UPDATE"], BATCH_SIZE)
    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                clust = line.split(" ")
                ref_ch_id = clust[0]
                if not re.match(r"^[1-9].{3}_.*$", ref_ch_id):
                    continue
                logging.info(f"Cluster {cl_id} reference chain: {ref_ch_id}, adding {len(clust)} members")
                for chain_id in clust:
                    # Skip chains that don't match the expected pattern
                    if not re.match(r"^[1-9].{3}_.*$", chain_id):
                        continue
                    bulk.append(
                        {"_id": chain_id},
                        {"$set": {f"sqclusters.{cl_id}": ref_ch_id}},
                        chain_id,
                    )
                    bulk.commit_data_if_full()
        bulk.commit_any_data()
    except IOError as e:
        print_log(f"Error reading cluster file {file_path}: {e}")


def load_entries(entries_col, tstamp, classes):
    """Load basic PDB entry fields from entries.idx."""
    print_log("Entries...")
    bulk = MongoDBBulkWrite(entries_col, CTS["UPSERT"], BATCH_SIZE)
    with open_text_file(PATHS["ENTRIES"]) as fh:
        for line in fh:
            line = line.rstrip("\n")
            parts = line.split("\t")
            if len(parts) < 8:
                continue
            id_code, header, asc_date, compound, _, _, resol, exp_type = parts[:8]
            if len(id_code) != 4:
                continue
            exp_type = exp_type.replace(" ", "_")
            exp_type = exp_type.split(",", 1)[0]
            if not exp_type:
                exp_type = "NA"
            if exp_type not in classes:
                classes[exp_type] = exp_type
            bulk.append(
                {"_id": id_code},
                {
                    "$set": {
                        "_id": id_code,
                        "header": header,
                        "compound": compound,
                        "ascDate": asc_date,
                        "resol": resol,
                        "expType": exp_type,
                        "expClass": classes[exp_type],
                        "stamp": tstamp,
                    }
                },
                id_code,
            )
            bulk.commit_data_if_full()
    bulk.commit_any_data()


def load_authors(entries_col):
    """Append author names to PDB entry documents."""
    print_log("Authors...")
    bulk = MongoDBBulkWrite(entries_col, CTS["UPDATE"], BATCH_SIZE)
    with open_text_file(PATHS["AUTSF"]) as fh:
        for line in fh:
            if ";" not in line:
                continue
            line = line.strip()
            parts = re.split(r" *; *", line, maxsplit=1)
            if len(parts) != 2:
                continue
            id_code, author = parts
            if not author:
                continue
            bulk.append(
                {"_id": id_code},
                {"$addToSet": {"authors": author}},
                id_code,
            )
            bulk.commit_data_if_full()
    bulk.commit_any_data()
    print_log("ok")


def load_sources(entries_col):
    """Append source names to PDB entry documents."""
    print_log("Sources...")
    bulk = MongoDBBulkWrite(entries_col, CTS["UPDATE"], BATCH_SIZE)
    with open_text_file(PATHS["SOURF"]) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ", 1)
            if len(parts) != 2:
                continue
            id_code, source = parts
            if not source or len(id_code) != 4:
                continue
            for _ in re.split(r"; *", source):
                bulk.append(
                    {"_id": id_code},
                    {"$addToSet": {"sources": source.upper()}},
                    id_code,
                )
                bulk.commit_data_if_full()
    bulk.commit_any_data()
    print_log("ok")


def load_comp_types(entries_col):
    """Load entry composition types."""
    print_log("Comp Types...")
    bulk = MongoDBBulkWrite(entries_col, CTS["UPDATE"], BATCH_SIZE)
    with open_text_file(PATHS["CTYPEF"]) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split(" ")
            if len(parts) < 2:
                continue
            id_code, comp_type = parts[:2]
            id_code = id_code.upper()
            bulk.append(
                {"_id": id_code},
                {"$set": {"compType": comp_type}},
                id_code,
            )
            bulk.commit_data_if_full()
    bulk.commit_any_data()
    print_log("ok")


def load_sequences(entries_col, chains_col, sequences_col):
    """Load chain sequences and related metadata from seqres fasta."""
    print_log("Sequences...")
    seq = ""
    id_code = ""
    chain = ""
    header = ""
    seq_type = ""
    entries_bulk = MongoDBBulkWrite(entries_col, CTS["UPDATE"], BATCH_SIZE)
    chains_upsert = MongoDBBulkWrite(chains_col, CTS["UPSERT"], BATCH_SIZE)
    chains_update = MongoDBBulkWrite(chains_col, CTS["UPDATE"], BATCH_SIZE)
    sequences_upsert = MongoDBBulkWrite(sequences_col, CTS["UPSERT"], BATCH_SIZE)

    def flush_seq():
        nonlocal seq, id_code, chain, header, seq_type
        if not seq:
            return
        seq = seq.replace("\n", "")
        id_code = id_code.upper()
        chain = chain.replace(" ", "")
        chain_id = f"{id_code}_{chain}"
        entries_bulk.append(
            {"_id": id_code},
            {"$addToSet": {"chainIds": chain_id}},
            id_code,
        )
        chains_upsert.append(
            {"_id": chain_id},
            {"$set": {"_id": chain_id, "type": seq_type, "header": header}},
            chain_id,
        )
        seq_x = seq.replace("X", "")
        if seq_type == "protein" and len(seq_x) > 20:
            chains_update.append(
                {"_id": chain_id},
                {"$set": {"sqclusters.bc-100": chain_id}},
                chain_id,
            )
        sequences_upsert.append(
            {"_id": chain_id},
            {
                "$set": {
                    "_id": chain_id,
                    "sequence": seq,
                    "type": seq_type,
                    "origin": "pdb",
                }
            },
            chain_id,
        )
        entries_bulk.commit_data_if_full()
        chains_upsert.commit_data_if_full()
        chains_update.commit_data_if_full()
        sequences_upsert.commit_data_if_full()
        seq = ""

    with open_text_file(PATHS["SEQFASTAF"]) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith(">"):
                flush_seq()
                match = re.match(r">([^_]*)_(.*)mol:(\S*) length:(\S*) (.*)", line)
                if not match:
                    continue
                id_code, chain, seq_type, length, rest = match.groups()
                header = f"{id_code} {chain} {seq_type} {length} {rest}"
            else:
                seq += line
    flush_seq()
    entries_bulk.commit_any_data()
    chains_upsert.commit_any_data()
    chains_update.commit_any_data()
    sequences_upsert.commit_any_data()
    print_log("ok")


def load_obsoletes(entries_col, chains_col, sequences_col, tstamp):
    """Mark obsolete entries and remove their chain/sequence data."""
    print_log("Obsolete entries...")
    entries_bulk = MongoDBBulkWrite(entries_col, CTS["UPSERT"], BATCH_SIZE)
    chains_del = MongoDBBulkWrite(chains_col, CTS["DELETE"], BATCH_SIZE)
    sequences_del = MongoDBBulkWrite(sequences_col, CTS["DELETE"], BATCH_SIZE)
    with open_text_file(PATHS["OBSF"]) as fh:
        _ = next(fh, None)
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            _, asc_date, id_code = parts[:3]
            supersby = parts[3] if len(parts) > 3 else None
            if id_code and not supersby:
                supersby = "None"
            if supersby:
                pdb = entries_col.find_one({"_id": id_code}, {"chainIds": 1}) or {}
                for ch in pdb.get("chainIds", []):
                    chains_del.append({"_id": ch}, None, ch)
                    sequences_del.append({"_id": ch}, None, ch)
                    chains_del.commit_data_if_full()
                    sequences_del.commit_data_if_full()
                entries_bulk.append(
                    {"_id": id_code},
                    {
                        "$set": {
                            "ascDate": asc_date,
                            "supersby": supersby,
                            "header": "Superseeded",
                            "stamp": tstamp,
                        },
                        "$unset": {"hetAtms": 1, "chainIds": 1, "remarks": 1},
                    },
                    id_code,
                )
                entries_bulk.commit_data_if_full()
    entries_bulk.commit_any_data()
    chains_del.commit_any_data()
    sequences_del.commit_any_data()
    print_log("ok")


def load_monomers(monomers_col):
    """Load monomer reference data from the het dictionary."""
    print_log("Prep. monomers table...")
    weights = {}
    with open_text_file(PATHS["MWTABF"]) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            el, mw = line.split()
            weights[el.lower()] = float(mw)

    txt = ""
    syn = ""
    form = ""
    nom = ""
    long_val = ""
    cont = False
    cont1 = False

    bulk = MongoDBBulkWrite(monomers_col, CTS["UPSERT"], BATCH_SIZE)
    with open_text_file(PATHS["MONF"]) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("RESIDUE"):
                if txt:
                    mw, car = calc_mw(form, weights)
                    bulk.append(
                        {"_id": nom},
                        {
                            "$set": {
                                "name": txt,
                                "nat": int(long_val) if long_val else 0,
                                "syn": syn,
                                "formul": form,
                                "mw": float(mw),
                                "charge": float(car),
                            }
                        },
                        nom,
                    )
                    bulk.commit_data_if_full()
                parts = line.split()
                nom = parts[1] if len(parts) > 1 else ""
                long_val = parts[2] if len(parts) > 2 else ""
                cont = False
                cont1 = False
                txt = ""
                syn = ""
                form = ""
            elif line.startswith("HETNAM"):
                if not cont:
                    parts = line.split()
                    if len(parts) == 3:
                        _, _, txt = parts
                    cont = True
                else:
                    parts = line.split()
                    if len(parts) == 4:
                        txt += parts[3]
            elif line.startswith("HETSYN"):
                if not cont1:
                    parts = line.split()
                    if len(parts) == 3:
                        _, _, syn = parts
                    cont1 = True
                else:
                    parts = line.split()
                    if len(parts) == 4:
                        syn += parts[3]
            elif line.startswith("FORMUL"):
                parts = line.split()
                if len(parts) == 3:
                    _, _, form = parts
    bulk.commit_any_data()


def load_hetatms(entries_col, todo, data_gfs):
    """Scan CIF files for HETATM codes"""
    bulk = MongoDBBulkWrite(entries_col, CTS["UPDATE"], BATCH_SIZE)
    codes = entries_col.find({"supersby": {"$exists": 0}}, {"_id": 1})
    print_log(f"Reading {len(codes)} CIFs...")
    for pdbdata in codes:
        id_code = pdbdata.get("_id")
        if not id_code:
            continue
        id_code_lc = id_code.lower()
        filename = f"{id_code_lc}.cif.gz"
        try:
            stream = data_gfs.open_download_stream_by_name(filename)
            gz = gzip.GzipFile(fileobj=stream, mode='rb')
            fh = io.TextIOWrapper(gz, encoding='utf-8')
        except gridfs.errors.NoFile:
            logging.error(f"File not found in GridFS for {id_code}: {filename}")
            continue
        hets = set()
        for line in fh:
            if not line.startswith("HETATM"):
                continue
            if len(line.split()) < 6:
                logging.warning(f"Found unusual HETATM line {line} at {id_code}")
                continue
            cod = line.split()[5]
            if cod == "HOH":
                continue
            if cod not in hets:
                hets.add(cod)
                logging.debug(f"Found HETATM code {cod} in {id_code}")
                bulk.append(
                    {"_id": id_code},
                    {"$addToSet": {"hets": cod}},
                    id_code,
                )
                bulk.commit_data_if_full()
        fh.close()
        gz.close()
        stream.close()
    bulk.commit_any_data()


def load_large(entries_col, chains_col, sequences_col):
    """Load large structure groups and prune member chains."""
    print_log("Large structures...")
    entries_bulk = MongoDBBulkWrite(entries_col, CTS["UPDATE"], BATCH_SIZE)
    entries_bulk_upsert = MongoDBBulkWrite(entries_col, CTS["UPSERT"], BATCH_SIZE)
    chains_del = MongoDBBulkWrite(chains_col, CTS["DELETE"], BATCH_SIZE)
    sequences_del = MongoDBBulkWrite(sequences_col, CTS["DELETE"], BATCH_SIZE)
    with open_text_file(PATHS["LARGEF"]) as fh:
        for line in fh:
            if line.startswith("Large"):
                continue
            line = line.strip()
            if not line:
                continue
            if ':' in line:
                continue
            parts = line.split( "\t", 1)
            if len(parts) != 2:
                continue
            ref, list_txt = parts
            parts_list = list_txt.split(",")
            entries_bulk.append(
                {"_id": ref},
                {"$set": {"groups": parts_list}},
                ref,
            )
            entries_bulk.commit_data_if_full()
            for entry_id in parts_list:
                entries_bulk_upsert.append(
                    {"_id": entry_id},
                    {
                        "$set": {"header": "Large structure, Grouped", "groupedby": ref},
                        "$unset": {"chainIds": 1, "hetAtms": 1},
                    },
                    entry_id,
                )
                entries_bulk_upsert.commit_data_if_full()
                pdb = entries_col.find_one({"_id": entry_id}, {"chainIds": 1}) or {}
                for ch in pdb.get("chainIds", []):
                    chains_del.append({"_id": ch}, None, ch)
                    sequences_del.append({"_id": ch}, None, ch)
                    chains_del.commit_data_if_full()
                    sequences_del.commit_data_if_full()
    entries_bulk.commit_any_data()
    entries_bulk_upsert.commit_any_data()
    chains_del.commit_any_data()
    sequences_del.commit_any_data()

def load_assemblies(assembly_col, entries_col, file_type='cif'):
    ''' load Assembly references'''
    print_log("Assemblies...")
    entries_bulk = MongoDBBulkWrite(entries_col, CTS["UPDATE"], BATCH_SIZE)
    logging.info("Clearing assembly data")
    entries_col.update_many({}, {'$unset': {"assemblies":1}})
    for file in assembly_col.find({}, projection={"filename":1}):
        if file_type not in file['filename']:
            continue
        assembly_id = file['filename'].replace('.cif.gz', '')
        pdb_id, _ = assembly_id.split('-')
        entries_bulk.append(
                {"_id": pdb_id.upper()},
                {"$addToSet": {"assemblies": assembly_id}}
        )
        entries_bulk.commit_data_if_full()
    entries_bulk.commit_any_data()

    


def main():
    """Parse arguments and run selected load operations."""
    cmd = argparse.ArgumentParser(
        description="PDB loader"
    )
    cmd.add_argument("ops", nargs="*", help="Operations: ALL|ALL_BUT_ENTRIES|ENTRIES|AUTSF|SOURF|CTYPEF|SEQFASTAF|OBSF|MONF|HETATM|REMARKS|CLUSTERS|LARGE")
    cmd.add_argument("--host", default="localhost", help="MongoDB host (default: localhost)")
    cmd.add_argument("--database", default="FlexPortal", help="MongoDB database (default: FlexPortal)")
    cmd.add_argument("--mirror", default=DEFAULT_MIRROR, help="Path to mirror directory (default: /data/dbmirror)")
    cmd.add_argument("--clear_entries", action="store_true", help="Delete all data from collections before loading")
    cmd.add_argument("--bucket", help="GridFS bucket name", default="PDB_DataFiles")
    cmd.add_argument("--debug", action="store_true", help="Debug logging")
    args = cmd.parse_args()

    # Populate PATHS dict based on mirror directory
    mirror_path = args.mirror
    datadir = f"{mirror_path}/data"
    mirrorpdb = f"{mirror_path}/sites/ftp.wwpdb.org/pub/pdb"
    dbprefix = f"{mirrorpdb}/derived_data"

    PATHS["EXPTYPES"] = f"{datadir}/expTypes"
    PATHS["MWTABF"] = f"{datadir}/mwtable.txt"
    PATHS["ENTRIES"] = f"{dbprefix}/index/entries.idx"
    PATHS["AUTSF"] = f"{dbprefix}/index/author.idx"
    PATHS["SOURF"] = f"{dbprefix}/index/source.idx"
    PATHS["CTYPEF"] = f"{dbprefix}/pdb_entry_type.txt"
    PATHS["SEQFASTAF"] = f"{dbprefix}/pdb_seqres.txt"
    PATHS["OBSF"] = f"{mirrorpdb}/data/status/obsolete.dat"
    PATHS["MONF"] = f"{mirrorpdb}/data/monomers/het_dictionary.txt"
    PATHS["LARGEF"] = f"{mirrorpdb}/compatible/pdb_bundle/large_split_mapping.tsv"
    PATHS["CLUSTERS_DIR"] = f"{mirror_path}/sites/cdn.rcsb.org/resources/sequence/clusters"
    PATHS["PREFIX"] = f"{mirrorpdb}/data/structures/divided/pdb"

    todo = {op.upper(): 1 for op in args.ops}
    if "OBSF" in todo:
        todo["LARGE"] = 1
    if "ALL_BUT_ENTRIES" in todo:
        for op in ["AUTSF", "SOURF", "CTYPEF", "SEQFASTAF", "OBSF", "MONF", "HETATM", "REMARKS", "CLUSTERS", "LARGE", "HETATM", "ASSEMBLIES"]:
            todo[op] = 1

    logging.basicConfig(
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d|%H:%M:%S",
    )
    logging.getLogger().setLevel(10 if args.debug else 20)

    db_lnk = MongoDB(args.host, args.database, False, AUTH)
    cols = db_lnk.get_collections(["PDB_Entry", "chain", "sequences", "PDB_Monomers", "PDB_Assemblies.files"])
    entries_col = cols["PDB_Entry"]
    chains_col = cols["chain"]
    sequences_col = cols["sequences"]
    monomers_col = cols["PDB_Monomers"]
    assemblies_col = cols["PDB_Assemblies.files"]

    data_gfs = db_lnk.get_gfs(args.bucket)
    if data_gfs is None:
        logging.error("ERROR: Failed to connect to GridFS")
        return 1

    tstamp = int(datetime.now(timezone.utc).timestamp())
    print_log(f"Time stamp: {tstamp}")

    # Clear collections if requested
    if args.clear_entries:
        print_log("Clearing all collections...")
        entries_col.delete_many({})
        chains_col.delete_many({})
        sequences_col.delete_many({'origin:': 'pdb'})
        monomers_col.delete_many({})
        print_log("Collections cleared")

    classes = {}
    with open_text_file(PATHS["EXPTYPES"]) as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            parts = line.split("#")
            if len(parts) != 2:
                continue
            typ, cla = parts
            classes[typ] = cla

    if todo.get("ENTRIES") or todo.get("ALL"):
        load_entries(entries_col, tstamp, classes)
        print_log("Entries ok")

    if todo.get("AUTSF") or todo.get("ALL"):
        load_authors(entries_col)
        print_log("Authors ok")

    if todo.get("SOURF") or todo.get("ALL"):
        load_sources(entries_col)
        print_log("Sources ok")

    if todo.get("CTYPEF") or todo.get("ALL"):
        load_comp_types(entries_col)
        print_log("Compound types and metadata ok")

    if todo.get("SEQFASTAF") or todo.get("ALL"):
        load_sequences(entries_col, chains_col, sequences_col)
        print_log("Sequences ok")

    if todo.get("OBSF") or todo.get("ALL"):
        load_obsoletes(entries_col, chains_col, sequences_col, tstamp)
        print_log("Obsoletes ok")

    if todo.get("MONF") or todo.get("ALL"):
        load_monomers(monomers_col)
        print_log("Monomers ok")

    if todo.get("HETATM") or todo.get("ALL"):
        load_hetatms(entries_col, todo, data_gfs)
        print_log("HetAtoms ok")

    if todo.get("CLUSTERS") or todo.get("ALL"):
        for cl in AVAILABLE_CLUSTERS:
            print_log(f"CLuster bc-{cl}")
            load_cluster_bc(cl, chains_col)
        print_log("Clusters ok")

    if todo.get("CLUSTERS") or todo.get("ALL") or todo.get("SEQFASTAF"):
        print_log("Cluster bc-100")
        load_cluster_bc("100", chains_col)
        print_log("Cluster bc-100 ok")
    if todo.get("ALL") or todo.get("LARGE"):
        load_large(entries_col, chains_col, sequences_col)
        print_log("Large structures ok")
    if todo.get("ASSEMBLIES") or todo.get("ALL"):
        load_assemblies(assemblies_col, entries_col, file_type="cif")
        print_log("Assemblies ok")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
