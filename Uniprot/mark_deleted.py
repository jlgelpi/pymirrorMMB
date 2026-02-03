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
db_cols = db_lnk.get_collections(["headers", "sequences", "Annotation", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

if args.debug:
    logging.getLogger().setLevel(10)
else:
    logging.getLogger().setLevel(20)

logging.info("Markng deleted entries")

headDelBuff = MongoDBBulkWrite(db_cols['headers'],CTS['DELETE'], BATCH_SIZE)
headUpdBuff = MongoDBBulkWrite(db_cols['headers'],CTS['UPDATE'], 3*BATCH_SIZE)
seqBuff = MongoDBBulkWrite(db_cols['sequences'], CTS['DELETE'], BATCH_SIZE)
annotBuff = MongoDBBulkWrite(db_cols['Annotation'], CTS['DELETE'], BATCH_SIZE)


if args.ini_line:
    logging.info('Starting at line {}'.format(args.ini_line))
if args.fin_line:
    logging.info('Stopping at line {}'.format(args.fin_line))

logging.info('Reading input files')

for file in args.files:
    
    logging.info('Processing ' + file)

    f_mgr = FileMgr(file, args.ini_line, args.fin_line)

    if args.tupd and not f_mgr.check_new_stamp(db_cols['fileStamps']):
        logging.info("File not new, skipping")
        continue
    
    f_mgr.open_file()
    
    if args.inic:
        logging.info("Skipping until {} ".format(args.inic))
        f_mgr.skip_lines_to(args.inic, True)
    else:
        f_mgr.skip_lines_to('______')
    
    f_mgr.skip_lines_to_ini()
    
    for line in f_mgr:
        if line.find('_____') != -1:
            continue
        if not len(line):
            break
        id = line
        for buff in headDelBuff, seqBuff, annotBuff:
            buff.append({'_id': id},{})
            buff.commit_data_if_full()
            
        for ref in 'UniRef100','UniRef90','UniRef50':
            headUpdBuff.append(
                {'dbxref.'+ref: id},
                {'$pullAll':{'dbxref.'+ ref: [id]}}
            )

        headUpdBuff.commit_data_if_full(True);

    for buff in headDelBuff, seqBuff, annotBuff:
        buff.commit_any_data()

    headUpdBuff.commit_any_data(True)

    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    
    del f_mgr

logging.info('Mark deleted Done')

logging.info(headDelBuff.global_stats())

logging.info(headUpdBuff.global_stats())

logging.info(seqBuff.global_stats())

logging.info(annotBuff.global_stats())

