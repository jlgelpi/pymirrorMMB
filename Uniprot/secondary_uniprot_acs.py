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
cmd.add_argument('--ini_line', dest='ini_line', type=int, default=0, required=False, help='Initial line to process')
cmd.add_argument('--fin_line', dest='fin_line', type=int, default=0, required=False, help='Final line ot process')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process (FASTA(.gz))")
args = cmd.parse_args()

db_lnk = MongoDB('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["headers", "sequences", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')
if args.debug:
    logging.getLogger().setLevel(10)
else:
    logging.getLogger().setLevel(20)

logging.info("Adding secondary accessions")

headBuff = MongoDBBulkWrite(db_cols['headers'],CTS['UPSERT'], BATCH_SIZE)
seqBuff = MongoDBBulkWrite(db_cols['sequences'], CTS['DELETE'], BATCH_SIZE/2)

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
    
    f_mgr.skip_lines_to('_____')
    
    f_mgr.skip_lines_to_ini()

    for line in f_mgr:
        if line.find('_____') != -1:
            continue
        sec_ac, ac_num = re.split('\W+', line)
        
        headBuff.append(
            {'_id':sec_ac},
            {'$set': 
                {
                    'isSecondary' : 1,
                    'refAc' : ac_num,
                    'stamp' : f_mgr.tstamp
                }
            }
        )
            
        headBuff.append(
            {'_id':ac_num},
            {'$addToSet' : {'secAcs': sec_ac}}
        )
        seqBuff.append({'_id':sec_ac},{});
            
        headBuff.commit_data_if_full()
        seqBuff.commit_data_if_full()
        db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
        
    headBuff.commit_any_data()
    seqBuff.commit_any_data()

    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    del f_mgr

logging.info('load Secondaries Done')

logging.info(headBuff.global_stats())

logging.info(seqBuff.global_stats())

