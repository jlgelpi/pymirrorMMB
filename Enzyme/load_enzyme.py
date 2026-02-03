#!/usr/bin/env python3
#encoding: UTF-8

# To change this license header, choose License Headers in Project Properties.
# To change this template file, choose Tools | Templates
# and open the template in the editor.

import argparse
import logging
import os
import re
import gzip
import sys

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite
from mmb_data.file_mgr import FileMgr
import mmb_data.utils as ut

BATCH_SIZE = 100000
AUTH = True

def procesa(data_obj, cols):
    cols['enzyme'].update_one (
	    {'_id': data_obj['_id']},
            {'$set' : data_obj },
            upsert=True
    )
    for acc in data_obj['uniprotIds']:
        cols['headers'].update_one (
            {'_id' : acc},
            {'$addToSet' : 
                {
                    'dbxref.EC' : data_obj['_id']
                }
            }
        )


cmd = argparse.ArgumentParser(
    description='Uniprot Fasta loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process (dat.gz))")
args = cmd.parse_args()

db_lnk = MongoDB('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["enzyme", "headers", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

headBuff = MongoDBBulkWrite(db_cols['headers'],CTS['UPSERT'], BATCH_SIZE)

if args.debug:
    logging.getLogger().setLevel(10)
else:
    logging.getLogger().setLevel(20)

logging.info('Reading sources...')

data_obj = {}
nupd = 0

for file in args.files:
    logging.info('Processing ' + file)

    f_mgr = FileMgr(file, 0,0)

    if args.tupd and not f_mgr.check_new_stamp(db_cols['fileStamps']):
        logging.info("File not new, skipping")
        del f_mgr
        continue
    
    f_mgr.open_file()
    
    for line in f_mgr:
        if line in ('//', 'CC'):
            continue
        (lb, data_str) = line.split(' ',1)
        if (lb == 'CC') and '_id' not in data_obj:
            continue
        data_str = data_str.strip()
        if lb == 'ID':
            if '_id' in data_obj:
                procesa(data_obj, db_cols);
                nupd += 1
                if args.verb:
                    logging.info(data_obj['_id'])
            data_obj = {
                '_id' : data_str,
                'altNames' : [],
                'uniprotIds' : [],
                'stamp' : f_mgr.tstamp,
                'activity' : '',
                'comment' : '',
                'prositeDocs': []
            }
        elif lb == 'DR':
            dbdata = re.split('; *', data_str)
            for f in dbdata:
                if not f:
                    continue
                a,b = re.split(', *', f)
                data_obj['uniprotIds'].append(a)
        elif lb == 'DE':
            data_obj['description'] = data_str
        elif lb == 'AN':
            data_obj['altNames'].append(data_str)
        elif lb == 'CF':
            data_obj['cofactor'] = data_str
        elif lb == 'CA':
            data_obj['activity'] += data_str + " "
        elif lb == 'CC':
            data_obj['comment'] += data_str + " ";
        elif lb == 'PR':
            a, b  = re.split('; *', data_str, 1)
            data_obj['prositeDocs'].append(b)

    if data_obj:
        procesa(data_obj, db_cols)
        nupd += 1
    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)    
logging.info("Done. {} records".format(nupd))

