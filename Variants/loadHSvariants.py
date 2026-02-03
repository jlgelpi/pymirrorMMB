""" Import Ensembl variants"""

import argparse
import logging
import os
import gzip
import sys

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite
from mmb_data.file_mgr import FileMgr
import mmb_data.utils as ut

BATCH_SIZE = 50000
AUTH = True

cmd = argparse.ArgumentParser(
    description='Uniprot Variants loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('--inic', dest='inic', required=False, help='Initial id to process')
cmd.add_argument('--skip_ids', dest='skip', type=int, required=False, default=0, help='Skip records')
cmd.add_argument('--ini_line', dest='ini_line', type=int, default=0, required=False, help='Initial line to process')
cmd.add_argument('--fin_line', dest='fin_line', type=int, default=0, required=False, help='Final line ot process')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process")
args = cmd.parse_args()

db_lnk = MongoDB('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["variants", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

varBuff = MongoDBBulkWrite(db_cols['variants'],CTS['UPSERT'], BATCH_SIZE)

if args.debug:
    logging.getLogger().setLevel(10)
else:
    logging.getLogger().setLevel(20)

if args.skip:
    logging.info('Skipping {} records'.format(args.skip))
if args.inic:
    logging.info('Skipping until {}'.format(args.inic))
if args.ini_line:
    logging.info('Starting at line {}'.format(args.ini_line))
if args.fin_line:
    logging.info('Stopping at line {}'.format(args.fin_line))

logging.info('Reading input files...')

for file in args.files:
    logging.info('Processing ' + file)
        
    f_mgr = FileMgr(file, args.ini_line, args.fin_line)

    if args.tupd and not f_mgr.check_new_stamp(db_cols['fileStamps']):
        logging.info("File not new, skipping")
        del f_mgr
        continue
    
    f_mgr.open_file()
    
    if args.inic:
        logging.info("Skipping until {} ".format(args.inic))
        f_mgr.skip_lines_to(args.inic, True)
    else:
        f_mgr.skip_lines_to('######## VARIANT INDEX ########', True)
    
    f_mgr.skip_n_lines(2)
    
    f_mgr.skip_lines_to_ini()
    
    for line in f_mgr:
        if not len(line):
            break
    
##Gene Name       AC              Variant AA Change       Source DB ID    Consequence Type        Clinical Significance   Phenotype/Disease       Phenotype/Disease Source Cytogenetic Band        Chromosome Coordinate   Ensembl gene ID         Ensembl transcript ID   Ensembl translation ID
##_________       __________      _________________       ____________    ________________        _____________________   _________________       ________________________ ________________        _____________________   ____________________    _____________________   ______________________
##A1BG    M0R009  p.Thr2Met       rs7256067       missense variant        -       -       -       19q13.43        19:g.58864491G>A        ENSG00000121410  ENST00000600966 ENSP00000470909
        data = line.split("\t")
#        print(data)
        if len(data) < 10:
            continue
        varBuff.append(
            {'_id':{'ac':data[1],'mut':data[2]}},
            {
                '$set' : {
                    'gn': data[0],
                    'ENSG' : data[10],  
                    'cyto' : data[8],
                },
                '$addToSet': {
                    'variants': {
                        'varorig':'ensembl', 
                        'varId': data[3],
                        'type': data[4],
                        'consequence': data[4],
                        'dbId' : data[3],
                        'phenotype' : {'desc' : data[6],'source': data[7]},
                        'clinical': data[5],
                        'ENST': data[11],
                        'ENSP': data[12],
                        'dnamut': data[9],
                    }
                }
            }
        )
      
        logging.debug("{} {} {}".format(f_mgr.current_line, data[1], data[2]))
        varBuff.commit_data_if_full(True)

    varBuff.commit_any_data(True)

    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    
    del f_mgr

logging.info('Ensembl Variants Done')

logging.info(varBuff.global_stats())
