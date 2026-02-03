import argparse
import logging
import os
import gzip
import sys
import re

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite
from mmb_data.file_mgr import FileMgr

BATCH_SIZE = 100000
AUTH = True


cmd = argparse.ArgumentParser(
    description='Uniprot Secondary Accession loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('--inic', dest='inic', required=False, help='Initial id to process')
cmd.add_argument('--ini_line', dest='ini_line', type=int, default=0, required=False, help='Initial line to process')
cmd.add_argument('--fin_line', dest='fin_line', type=int, default=0, required=False, help='Final line ot process')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process (FASTA(.gz))")
args = cmd.parse_args()

db_lnk = MongoDB('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["headers", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')
if args.debug:
    logging.getLogger().setLevel(10)
else:
    logging.getLogger().setLevel(20)

logging.info("Adding id mappings")

headBuff = MongoDBBulkWrite(db_cols['headers'],CTS['UPDATE'], BATCH_SIZE)

logging.info('Reading input files')

if args.ini_line:
    logging.info('Starting at {} line'.format(args.ini_line))
if args.fin_line:
    logging.info('Stopping at {} line'.format(args.fin_line))

in_process = False
last_id = '-1'

for file in args.files:
    logging.info('Processing ' + file)

    f_mgr = FileMgr(file, args.ini_line, args.fin_line)
    
    if args.tupd and not f_mgr.check_new_stamp(db_cols['fileStamps']):
        logging.info("File not new, skipping")
        continue
    
    f_mgr.open_file()
    
     
    if args.inic:
        logging.info("Skipping until {} ".format(args.inic))
        f_mgr.skip_lines_to('^'+args.inic, True)
    
    f_mgr.skip_lines_to_ini()
    a = ''    
    for line in f_mgr:
        ac,db,id = line.split(None, 2)
        if db in ('PDB', 'UniRef100', 'UniRef90', 'UniRef50', 'Ensembl', 'GI', 'RefSeq_NT'): 
            if db != 'RefSeq_NT':
                id = re.sub('[^_]*_','',id);
            headBuff.append (
                {'_id' : ac},
                {'$addToSet': {"dbxref."+db : id}}
            )
            if args.verb and a != ac:
                logging.info("lin ac db") 
            a = ac
            headBuff.commit_data_if_full()

    headBuff.commit_any_data();
    
    del f_mgr

logging.info('load mappings Done')

logging.info(headBuff.global_stats())


