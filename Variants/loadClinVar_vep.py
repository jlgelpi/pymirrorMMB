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

BATCH_SIZE = 50000
AUTH = True

cmd = argparse.ArgumentParser(
    description='ClinVar Variants loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process")
args = cmd.parse_args()

db_lnk = MongoDB('mdb-login.bsc.es', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["variants", "variantsClinVar", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

varBuff = MongoDBBulkWrite(db_cols['variants'],CTS['UPSERT'], BATCH_SIZE)
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
    
    f_mgr.open_file()
    
    ids = set()
    
    for line in f_mgr:
        if line[0] == '#':
            continue
#Uploaded_variation     Location        Allele  Gene    Feature Feature_type    Consequence     cDNA_position   CDS_position    Protein_position        Amino_acids     Codons  Existing_variation       Extra                 
        data = line.split("\t")
        extra = {}
        for pair in data.pop().split(';'):
            k, v = pair.split('=')
            extra[k] = v
        data = data +  [''] * 10

        for mth in ('SIFT','PolyPhen'):
            if mth in extra:
                m = re.match('([^\(]*)\(([^\)]*)\)', extra[mth])
                extra[mth] = {'prediction': m.group(1), 'score': m.group(2)}
        if 'DOMAINS' in extra:
            doms = []
            for item in extra['DOMAINS'].split(','):
                ns, id = item.split(':',1)
                doms.append({ns : id})
            extra['DOMAINS'] = doms
        
        data[6] = data[6].split(',')
        
        ids.add(data[0])
        
        obj = {
            '_id':data[0],
            'location': data[1],
            'allele': data[2],
            'gene': data[3]
        }
        feature = {
            'feature': data[4],
            'feature_type': data[5],
            'consequence': data[6],
            'cDNA_pos': data[7],
            'CDS_pos': data[8],
            'Prot_pos': data[9],
            'amino_acids': data[10],
            'codons': data[11],
            'existing_vars': data[12].split(','),
            'extra': extra
        }
        varBuff.append(
            {'_id': obj['_id']},
            {
                '$set': obj, 
                '$addToSet': {'features':feature}
            }
        )
      
        logging.debug("{} {} {}".format(f_mgr.current_line, data[1], data[2]))
        varBuff.commit_data_if_full(True)

    varBuff.commit_any_data(True)

    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    
    del f_mgr

logging.info('ClinVar Variants Done')

logging.info(varBuff.global_stats())
