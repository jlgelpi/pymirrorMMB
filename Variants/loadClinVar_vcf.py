""" Import ClinVar variants from VCF"""

import argparse
import logging
import os
import gzip
import sys
import re
import vcf

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite
from mmb_data.file_mgr import FileMgr
import mmb_data.utils as ut

BATCH_SIZE = 10000
AUTH = False

cmd = argparse.ArgumentParser(
    description='ClinVar Variants loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process")
args = cmd.parse_args()

db_lnk = MongoDB('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["variantsClinVar", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

varBuff = MongoDBBulkWrite(db_cols['variantsClinVar'],CTS['UPSERT'], BATCH_SIZE)

if args.debug:
    logging.getLogger().setLevel(10)
else:
    logging.getLogger().setLevel(20)

logging.info('Reading input files...')

for file in args.files:
    logging.info('Processing ' + file)
        
    f_mgr = FileMgr(file, 0,0)

    if args.tupd and not f_mgr.check_new_stamp(db_cols['fileStamps']):
        logging.info("File not new, skipping")
        del f_mgr
        continue
    
    vcf_reader = vcf.Reader(open(file,'r'))
    for record in vcf_reader:
        obj = {
            '_id':record.ID,
            'chrom': record.CHROM,
            'ref': record.REF,
            'alt': list(map(str, record.ALT)),
            'info': record.INFO
            
        }
        varBuff.append(
            {'_id': obj['_id']},
            {
                '$set': obj, 
            }
        )
      
        #logging.debug("{} {} {}".format(f_mgr.current_line, record.ID, data[2]))
        varBuff.commit_data_if_full(True)

    varBuff.commit_any_data(True)

    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    
    del f_mgr

logging.info('ClinVar Variants Done')

logging.info(varBuff.global_stats())
