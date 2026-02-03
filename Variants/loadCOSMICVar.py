""" Import ClinVar variants"""

import argparse
import logging
import os
import gzip
import sys
import re

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite
from mmb_data.file_mgr import FileMgr
import mmb_data.utils as ut

BATCH_SIZE = 10000
AUTH = True

cmd = argparse.ArgumentParser(
    description='COSMIC Variants loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process")
args = cmd.parse_args()

db_lnk = MongoDB('mdb-login.bsc.es', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["variants", "variantsCosmic", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

varBuff = MongoDBBulkWrite(db_cols['variants'],CTS['UPSERT'], BATCH_SIZE)
varBuff = MongoDBBulkWrite(db_cols['variantsCosmic'],CTS['UPSERT'], BATCH_SIZE)

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
    
    f_mgr.open_file()
    f_mgr.skip_n_lines(1)
    ids = set()
    
    for line in f_mgr:
        data = line.split("\t")
        if '_' in data[0]:
            (gene_name, enst) = data[0].split('_')
        else:
            gene_name = data[0]
        id = data[16]
        if not id:
            print(data)
            id = data[17]
            if not id:
                sys.exit()
        while len(data) <= 36:
            data.append('')
            
        obj = {
            'Sample_name': data[4],
            'id_sample': data[5],
            'id_tumour': data[6],
            'primary': {
                'site': data[7],
                'subtypes' : data[8:11],
                'histology': data[11],
                'hist_sub' : data[12:15]
            },
            'GWScreen' : data[15],
            'mut_zygosity': data[22],
            'LOH': data[23],
            'resist_mut': data[28],
            'mut_somatic': data[31],
            'pubmed_id': data[32],
            'study_id': data[33],
            'tumour_origin': data[35],
            'age': data[36],
        }
        #print(obj)
        if obj['id_sample'] not in ids:
            varBuff.append(
                {'_id': id},
                {'$push' :{'cases': obj}}
            )
            ids.add(obj['id_sample'])
        
        logging.debug("{} {} {}".format(f_mgr.current_line, data[1], data[2]))
        varBuff.commit_data_if_full(True)

    varBuff.commit_any_data(True)

    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    
    del f_mgr

logging.info('ClinVar Variants Done')

logging.info(varBuff.global_stats())
