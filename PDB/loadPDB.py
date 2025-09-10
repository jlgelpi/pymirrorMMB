
import sys
import gzip
import datetime
import argparse
import re
import logging
from mmb_data.mongo_db_connect import Mongo_db

# Simple logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d|%H:%M:%S'
)

from mmb_data.mongo_db_connect import Mongo_db

AUTH=False

# --- MongoDB Connection ---
db_lnk = Mongo_db('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["PDB_Entry", "chain", "sequences", "PDB_Monomers", "fileStamps"])
entriesCol = db_cols['PDB_Entry']
chainsCol = db_cols['chain']
sequencesCol = db_cols['sequences']
monomersCol = db_cols['PDB_Monomers']

tstamp = int(datetime.datetime.now().timestamp())

# --- Helper Functions ---
def calcMW(form, M):
    mw = 0.0
    car = 0.0
    for tok in form.split():
        if '+' in tok or '-' in tok:
            sign = 1 if '+' in tok else -1
            tok = tok.replace('+', '').replace('-', '')
            car = sign * int(tok)
        else:
            m = re.match(r'([A-Za-z]+)([0-9]*)', tok)
            if m:
                el, num = m.group(1).lower(), int(m.group(2) or 1)
                if el not in M:
                    logging.warning(f"Element -{el}- not found ({form})")
                else:
                    mw += M[el] * num
    return mw, car

def condOpen(fn):
    if fn.endswith('.gz'):
        return gzip.open(fn, 'rt', encoding='utf-8')
    else:
        return open(fn, 'r', encoding='utf-8')


def loadClustercl(cl, CLUSTERS):
    file = f"{CLUSTERS}/clusters{cl}.txt"
    clId = f"cl-{cl}"
    refChId = None
    try:
        with open(file, encoding='utf-8') as clf:
            for line in clf:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                _id, oid, chain_id = parts[:3]
                chain_id = chain_id.replace(':', '_')
                if oid == '1':
                    refChId = chain_id
                idPdb = chain_id[:4]
                chainsCol.update_one(
                    {'_id': chain_id},
                    {'$set': {f'sqclusters.{clId}': refChId}}
                )
    except FileNotFoundError:
        logging.error(f"File not found: {file}")

def loadClusterbc(cl, CLUSTERS):
    file = f"{CLUSTERS}/bc-{cl}.out"
    clId = f"bc-{cl}"
    try:
        with open(file, encoding='utf-8') as clf:
            for line in clf:
                line = line.strip()
                if not line:
                    continue
                clust = line.split()
                if not clust:
                    continue
                refChId = clust[0]
                for chain_id in clust:
                    chainsCol.update_one(
                        {'_id': chain_id},
                        {'$set': {f'sqclusters.{clId}': refChId}}
                    )
    except FileNotFoundError:
        logging.error(f"File not found: {file}")

# --- Main Logic ---

def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--mirror', type=str, default='/data/dbmirror', help='Path to the mirror root directory')
    parser.add_argument('ops', nargs='*', help='Operations to perform: ALL, ENTRIES, AUTSF, SOURF, CTYPEF, SEQFASTAF, OBSF, MONF, HETATM, REMARKS, CLUSTERS, LARGE')
    args = parser.parse_args()

    MIRROR = args.mirror
    DATADIR = "./data"
    MIRRORPDB = f"{MIRROR}/sites/ftp.wwpdb.org/pub/pdb"
    PREFIX = f"{MIRRORPDB}/data/structures/all/pdb"
    DBPREFIX = f"{MIRRORPDB}/derived_data"
    CLUSTERS = f"{MIRROR}/sites/resources.rcsb.org/sequence/clusters"
    EXPTYPES = f"{DATADIR}/expTypes"
    MWTABF = f"{DATADIR}/mwtable.txt"
    ENTRIES = f"{DBPREFIX}/index/entries.idx"
    AUTSF = f"{DBPREFIX}/index/author.idx"
    SOURF = f"{DBPREFIX}/index/source.idx"
    CTYPEF = f"{DBPREFIX}/pdb_entry_type.txt"
    SEQFASTAF = f"{DBPREFIX}/pdb_seqres.txt"
    OBSF = f"{MIRRORPDB}/data/status/obsolete.dat"
    MONF = f"{MIRRORPDB}/data/monomers/het_dictionary.txt"
    LARGEF = f"{MIRRORPDB}/compatible/pdb_bundle/large_split_mapping.tsv"

    # Load experiment type classes (expClass) from EXPTYPES
    CLASSE = {}
    try:
        with open(EXPTYPES, encoding='utf-8') as expt:
            for line in expt:
                line = line.strip()
                if not line:
                    continue
                typ_cla = line.split('#')
                if len(typ_cla) == 2:
                    typ, cla = typ_cla[0].strip(), typ_cla[1].strip()
                    CLASSE[typ] = cla
    except FileNotFoundError:
        logging.error(f"File not found: {EXPTYPES}") 

    ops_todo = {op: True for op in args.ops}
    if not ops_todo:
        parser.print_usage()
        sys.exit(1)
    if 'OBSF' in ops_todo:
        ops_todo['LARGE'] = True

    # Example: ENTRIES
    if 'ENTRIES' in ops_todo or 'ALL' in ops_todo:
        logging.info("Entries...")
        with open(ENTRIES, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                fields = line.split('\t')
                if len(fields) < 8 or len(fields[0]) != 4:
                    continue
                idCode, header, ascDate, compound, _, _, resol, expType = fields
                expType = expType.replace(' ', '_').split(',')[0] or "NA"
                expClass = CLASSE.get(expType, expType)
                entriesCol.update_one(
                    {'_id': idCode},
                    {'$set': {
                        "_id": idCode,
                        "header": header,
                        "compound": compound,
                        "ascDate": ascDate,
                        "resol": resol,
                        "expType": expType,
                        "expClass": expClass,
                        "stamp": tstamp
                    }},
                    upsert=True
                )
        logging.info("Entries ok")
    
    # AUTSF section: Add authors to entries
    if 'AUTSF' in ops_todo or 'ALL' in ops_todo:
        logging.info("Authors...")
        with open(AUTSF, encoding='utf-8') as f:
            for line in f:
                if ';' not in line:
                    continue
                line = line.strip()
                parts = line.split(';')
                if len(parts) < 2:
                    continue
                idCode, author = parts[0].strip(), parts[1].strip()
                if not author:
                    continue
                entriesCol.update_one(
                    {'_id': idCode},
                    {'$addToSet': {'authors': author}}
                )
        logging.info("ok")

    # SOURF section: Add sources to entries
    if 'SOURF' in ops_todo or 'ALL' in ops_todo:
        logging.info("Sources...")
        with open(SOURF, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split(' ', 1)
                if len(parts) != 2:
                    continue
                idCode, source = parts
                if not source or len(idCode) != 4:
                    continue
                for s in source.split(';'):
                    s = s.strip()
                    if s:
                        entriesCol.update_one(
                            {'_id': idCode},
                            {'$addToSet': {'sources': source}}
                        )
    logging.info("ok")

    # CTYPEF section: Add compType to entries
    if 'CTYPEF' in ops_todo or 'ALL' in ops_todo:
        logging.info("Comp Types...")
        with open(CTYPEF, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 2:
                    continue
                idCode, compType = parts[0], parts[1]
                idCode = idCode.upper()
                entriesCol.update_one(
                    {'_id': idCode},
                    {'$set': {'compType': compType}}
                )
    logging.info("ok")

    # SEQFASTAF section: Update chains and sequences
    if 'SEQFASTAF' in ops_todo or 'ALL' in ops_todo:
        logging.info("Sequences...")
        seq = ''
        idCode = ''
        chain = ''
        header = ''
        type_ = ''
        with open(SEQFASTAF, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('>'):
                    if seq:
                        seq = seq.replace('\n', '')
                        idCode = idCode.upper()
                        chain = chain.strip()
                        chainId = f"{idCode}_{chain}"
                        entriesCol.update_one(
                            {'_id': idCode},
                            {'$addToSet': {'chain': chainId}}
                        )
                        chainsCol.update_one(
                            {'_id': chainId},
                            {'$set': {
                                '_id': chainId,
                                'type': type_,
                                'header': header,
                            }},
                            upsert=True
                        )
                        seqX = seq.replace('X', '')
                        if type_ == 'protein' and len(seqX) > 20:
                            chainsCol.update_one(
                                {'_id': chainId},
                                {'$set': {f'sqclusters.bc-100': {chainId}}}
                            )
                        sequencesCol.update_one(
                            {'_id': chainId},
                            {'$set': {
                                '_id': chainId,
                                'sequence': seq,
                                'type': type_,
                                'origin': 'pdb'
                            }},
                            upsert=True
                        )
                        seq = ''
                    # Parse new header
                    m = re.match(r'^>([^_]*)_(.*)mol:(\S*) length:(\S*) (.*)', line)
                    if m:
                        idCode, chain, type_, _, header = m.groups()
                else:
                    seq += line
    logging.info("ok")
    
    # Obsoletes
    if ops_todo.get('OBSF') or ops_todo.get('ALL'):
        logging.info("Obsolete entries...")
        with open(OBSF) as obsf:
            next(obsf)  # skip header
            for line in obsf:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) < 3:
                    continue
                lab, ascDate, idCode = parts[:3]
                supersby = parts[3] if len(parts) > 3 else None
                if idCode and not supersby:
                    supersby = "None"
                if supersby:
                    pdb = entriesCol.find_one({'_id': idCode}, {'chainIds': 1})
                    if pdb and 'chainIds' in pdb:
                        for ch in pdb['chainIds']:
                            chainsCol.delete_one({'_id': ch})
                            sequencesCol.delete_one({'_id': ch})
                    entriesCol.update_one(
                        {'_id': idCode},
                        {
                            '$set': {
                                'ascDate': ascDate,
                                'supersby': supersby,
                                'header': 'Superseeded',
                                'stamp': tstamp,
                            },
                            '$unset': {
                                'hetAtms': "",
                                'chainIds': "",
                                'remarks': ""
                            }
                        },
                        upsert=True
                    )
    logging.info("ok")
    
    # PrepMonomers
    if ops_todo.get('MONF') or ops_todo.get('ALL'):
        logging.info("Prep. monomers table...")
        M = {}
        with open(MWTABF) as mwf:
            for line in mwf:
                line = line.strip()
                if not line:
                    continue
                e, mw = line.split()
                e = e.lower()
                M[e] = float(mw)
        with open(MONF) as monf:
            nom = txt = long = syn = form = mw = car = None
            key = nom = long = None
            cont = cont1 = 0
            for line in monf:
                line = line.strip()
                if not line:
                    continue
                if 'RESIDUE' in line:
                    if txt:
                        mw, car = calcMW(form)
                        mw = float(mw)
                        monomersCol.update_one(
                            {'_id': nom},
                            {'$set': {
                                'name': txt,
                                'nat': int(long) if long is not None else 0,
                                'syn': syn,
                                'formul': form,
                                'mw': float(mw),
                                'charge': float(car)
                            }},
                            upsert=True
                        )
                    key, nom, long = line.split()[:3]
                    cont = 0
                    cont1 = 0
                    txt = ""
                    syn = ""
                elif 'HETNAM' in line:
                    if not cont:
                        parts = line.split(' ', 2)
                        key = parts[0]
                        tt = parts[1] if len(parts) > 1 else ''
                        txt = parts[2] if len(parts) > 2 else ''
                        cont = 1
                    else:
                        parts = line.split(' ', 3)
                        txt0 = parts[3] if len(parts) > 3 else ''
                        txt += txt0
                elif line.startswith('HETSYN'):
                    if not cont1:
                        parts = line.split(' ', 2)
                        key = parts[0]
                        tt = parts[1] if len(parts) > 1 else ''
                        syn = parts[2] if len(parts) > 2 else ''
                        cont1 = 1
                    else:
                        parts = line.split(' ', 3)
                        syn0 = parts[3] if len(parts) > 3 else ''
                        syn += syn0
                elif 'FORMUL' in line:
                    parts = line.split(' ', 2)
                    key = parts[0]
                    tt = parts[1] if len(parts) > 1 else ''
                    form = parts[2] if len(parts) > 2 else ''
    logging.info("ok")
    
    # Read HETATM
    if ops_todo.get('HETATM') or ops_todo.get('REMARKS') or ops_todo.get('ALL'):
        if ops_todo.get('ALL'):
            ops_todo['HETATM'] = 1
            ops_todo['REMARKS'] = 1
        logging.info("Reading PDBs...")
        codes = list(entriesCol.find({'supersby': {'$exists': False}}, {'_id': 1}))
        for pdbdata in codes:
            idCode = pdbdata['_id']
            idCodelc = idCode.lower()
            pdb_path = f"{PREFIX}/pdb{idCodelc}.ent.gz"
            val = set()
            rems = set()
            try:
                import gzip
                with gzip.open(pdb_path, 'rt') as pdbf:
                    for line in pdbf:
                        if ops_todo.get('HETATM') and line.startswith('HET '):
                            cod = line[7:10].replace(' ', '')
                            val.add(cod)
                        if ops_todo.get('REMARKS') and line.startswith('REMARK'):
                            parts = line.split()
                            if len(parts) > 1 and parts[1].isdigit():
                                rems.add(parts[1])
            except FileNotFoundError:
                logging.info(f"File not found: {pdb_path}")
                continue
            if ops_todo.get('HETATM'):
                for het in val:
                    entriesCol.update_one(
                        {'_id': idCode},
                        {'$addToSet': {'hets': het}}
                    )
            if ops_todo.get('REMARKS'):
                for rem in rems:
                    if not rem:
                        continue
                    entriesCol.update_one(
                        {'_id': idCode},
                        {'$addToSet': {'remarks': rem}}
                    )
    logging.info("ok")
    # Clusters PDB
    if ops_todo.get('CLUSTERS') or ops_todo.get('ALL'):
        for cl in ['50', '70', '90', '95']:
            logging.info(f"Cluster {cl}")
            loadClustercl(cl, CLUSTERS)
        # Clusters Blast
        for cl in ['30', '40', '50', '70', '90', '95']:
            logging.info(f"CLuster bc-{cl}")
            loadClusterbc(cl, CLUSTERS)
        logging.info("Clusters ok")
    if ops_todo.get('CLUSTERS') or ops_todo.get('ALL') or ops_todo.get('SEQFASTAF'):
        logging.info("Cluster bc-100")
        loadClusterbc('100', CLUSTERS)
        logging.info("ok")


    # LARGE section (moved to end)
    if ops_todo.get('ALL') or ops_todo.get('LARGE'):
        logging.info("Large structures...")
        try:
            with open(LARGEF, encoding='utf-8') as lgf:
                for line in lgf:
                    line = line.strip()
                    if not line:
                        continue
                    ref, list_ = line.split(' ', 1)
                    parts = list_.split(',')
                    entriesCol.update_one(
                        {'_id': ref},
                        {'$set': {'groups': parts}},
                        upsert=True
                    )
                    for i in parts:
                        entriesCol.update_one(
                            {'_id': i},
                            {
                                '$set': {
                                    'header': 'Large structure, Grouped',
                                    'groupedby': ref
                                },
                                '$unset': {
                                    'chainIds': "",
                                    'hetAtms': ""
                                }
                            },
                            upsert=True
                        )
                        pdb = entriesCol.find_one({'_id': i}, {'chainIds': 1})
                        if pdb and 'chainIds' in pdb:
                            for ch in pdb['chainIds']:
                                chainsCol.delete_one({'_id': ch})
                                sequencesCol.delete_one({'_id': ch})
        except FileNotFoundError:
            logging.error(f"File not found: {LARGEF}")

    logging.info("Parse finished ok")

if __name__ == "__main__":
    main()
