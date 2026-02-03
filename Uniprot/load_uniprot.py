#!/usr/bin/env python3
#encoding: UTF-8

# To change this license header, choose License Headers in Project Properties.
# To change this template file, choose Tools | Templates
# and open the template in the editor.

import argparse
import logging
import os
import gzip
import sys

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite
from mmb_data.file_mgr import FileMgr
import mmb_data.utils as ut

BATCH_SIZE = 100000
AUTH = True

def process_fasta(header, seq):

    data = header.split(' ')

    db,uniq_id,entry_name = data[0].split('|')
    
    header_data = {}
    
    prev_field = 'protein_name'
    header_data[prev_field] = []
    for i in range(1, len(data)):
        if data[i].find('=') == -1:
            header_data[prev_field].append(data[i])
        else:
            label, val = data[i].split('=', 1)
            if label:
                prev_field = label
            header_data[prev_field] = [val]
    
    header_data = {k: ' '.join(header_data[k]) for k in header_data}
    
    header_data['db']= db.replace('>','')
    header_data['_id'] = uniq_id
    header_data['swpId'] = entry_name
    header_data['header'] = header
    header_data['isoform'] = (uniq_id.find('-') != -1)
    
    if header_data['OX'] not in sources:
        sources[header_data['OX']] = header_data['OS']
        db_cols['sources'].insert_one({'_id': header_data['OX'], 'source': header_data['OS']})
        logging.info ("New source found: {}".format(header_data['OS']))
    header_data['source'] = header_data['OX']
    del header_data['OX']
    del header_data['OS']
    
    seqBuff.append(
        {'_id': header_data['_id']},
        {'$set' : 
            {
                '_id' : header_data['_id'],
                'sequence' : seq,
                'type' :  'protein',
                'origin' :'uniprot'
            }
        },
        header_data['_id']
    )

    headBuff.append(
        {'_id' : header_data['_id']},
        {'$set': header_data},
        header_data['_id']
    )
    if header_data['isoform']:
        refId, n = header_data['_id'].split('-')
        headBuff.append (
            {'_id': refId}, 
            {'$addToSet' : {'isoforms': header_data['_id']}}
        )
    headBuff.commit_data_if_full()
    seqBuff.commit_data_if_full()
    

cmd = argparse.ArgumentParser(
    description='Uniprot Fasta loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('--inic', dest='inic', required=False, help='Initial id to process')
cmd.add_argument('--skip_ids', dest='skip', type=int, required=False, default=0, help='Skip records')
cmd.add_argument('--ini_line', dest='ini_line', type=int, default=0, required=False, help='Initial line to process')
cmd.add_argument('--fin_line', dest='fin_line', type=int, default=0, required=False, help='Final line ot process')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process (FASTA(.gz))")
args = cmd.parse_args()

db_lnk = MongoDB('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["headers", "sequences", "sources","fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

headBuff = MongoDBBulkWrite(db_cols['headers'],CTS['UPSERT'], BATCH_SIZE)
seqBuff = MongoDBBulkWrite(db_cols['sequences'], CTS['UPSERT'], BATCH_SIZE)

if args.debug:
    logging.getLogger().setLevel(10)
else:
    logging.getLogger().setLevel(20)

logging.info('Reading sources...')

sources = {}
for sc in db_cols['sources'].find():
    sources[sc['_id']] = sc['source']
    
logging.info('{} sources loaded'.format(len(sources)))

ntot = db_cols['headers'].estimated_document_count()

logging.info('Found {} documents'.format(ntot))

if args.skip:
    logging.info('Skipping {} records'.format(args.skip))
if args.inic:
    logging.info('Skipping until {}'.format(args.inic))
if args.ini_line:
    logging.info('Starting at line {}'.format(args.ini_line))
if args.fin_line:
    logging.info('Stopping at line {}'.format(args.fin_line))

logging.info('Reading input files...')

in_process = not args.inic and not args.skip

nids = 0

for file in args.files:
    logging.info('Processing ' + file)
        
    f_mgr = FileMgr(file, args.ini_line, args.fin_line)

    if args.tupd and not f_mgr.check_new_stamp(db_cols['fileStamps']):
        logging.info("File not new, skipping")
        del f_mgr
        continue
    
    f_mgr.open_file()
    
    f_mgr.skip_lines_to_ini()
    
    header = ''
    seq = ''
    
    for line in f_mgr:
        if not len(line):
            continue
        if line.find('>') == 0:
            nids  += 1

            in_process = in_process or\
                args.inic == ut.get_id(line) or\
                (args.skip and nids > args.skip) 
            
            if header and in_process:
                process_fasta(header, seq)
            
            header = line
            seq = ''
            ut.print_progress('Input ids', nids, ntot, BATCH_SIZE/2)
        else:
            seq += line
        
    
    if header and in_process:
        process_fasta(header, seq)
    
    headBuff.commit_any_data()
    seqBuff.commit_any_data()
    
    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    
    del f_mgr
    
logging.info('loadUniprot Done')

logging.info(headBuff.global_stats())

logging.info(seqBuff.global_stats())