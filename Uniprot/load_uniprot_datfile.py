#!/usr/bin/env python3
#encoding: UTF-8

from Bio import SwissProt
import pprint

import argparse
import logging
import os
import gzip
import sys

from mmb_data.mongo_db_connect import MongoDB
from mmb_data.mongo_db_bulk_write import CTS, MongoDBBulkWrite
from mmb_data.file_mgr import FileMgr
import mmb_data.utils as ut
from Bio.SeqFeature import UnknownPosition, ExactPosition

BATCH_SIZE = 100000
AUTH = True

cmd = argparse.ArgumentParser(
    description='Uniprot Fasta loader'
)

cmd.add_argument('--tupd', dest='tupd', action='store_true', required=False, help='New files only')
cmd.add_argument('--inic', dest='inic', required=False, help='Initial id to process')
cmd.add_argument('--skip_ids', dest='skip', type=int, required=False, default=0, help='Skip records')
cmd.add_argument('-v', dest='verb', action='store_true', required=False, help='Additional logging')
cmd.add_argument('--debug', dest='debug', action='store_true', required=False, help='Debug logging')
cmd.add_argument('files', nargs=argparse.REMAINDER, help="Files to process (FASTA(.gz))")

args = cmd.parse_args()

db_lnk = MongoDB('localhost', 'FlexPortal', False, AUTH)
db_cols = db_lnk.get_collections(["headers", "sequences", "sources","annotation", "fileStamps"])

logging.basicConfig(stream=sys.stdout, format='[%(asctime)s] %(levelname)s %(message)s', datefmt='%Y-%m-%d|%H:%M:%S')

headBuff = MongoDBBulkWrite(db_cols['headers'],CTS['UPSERT'], BATCH_SIZE)
seqBuff = MongoDBBulkWrite(db_cols['sequences'],CTS['UPSERT'], BATCH_SIZE)
annotBuff = MongoDBBulkWrite(db_cols['annotation'],CTS['UPSERT'], BATCH_SIZE)

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

logging.info('Reading input files...')

in_process = not args.inic and not args.skip

nids = 0

pp = pprint.PrettyPrinter(indent=4)

logging.info('Reading sources...')

sources = {}
for sc in db_cols['sources'].find():
    sources[sc['_id']] = sc['source']
    
logging.info('{} sources loaded'.format(len(sources)))

for file in args.files:
    logging.info('Processing ' + file)
        
    f_mgr = FileMgr(file, 0, 0)

    if args.tupd and not f_mgr.check_new_stamp(db_cols['fileStamps']):
        logging.info("File not new, skipping")
        del f_mgr
        continue
    
    f_mgr.open_file()
    
    for rec in SwissProt.parse(f_mgr.fh_in):
        rec._id = rec.accessions[0]
        rec.accessions = rec.accessions[1:]
        header_data = {
            '_id':rec._id,
            'OX': rec.taxonomy_id[0],
            'OS': rec.organism,
            'seqId': rec.entry_name,
            'secAcs': rec.accessions,
            'evidence': rec.protein_existence,
            'taxonomy_id': rec.taxonomy_id,
            'taxonomy_classification': rec.organism_classification,
            'keywords': rec.keywords,
            'comments': rec.comments,
            'description': rec.description,
            'created' : rec.created[0],
            'dbxref': {
                'UniRef100':[], 
                'UniRef90': [], 
                'UniRef50':[],
                'PDB':[], 
                'Ensembl':[]
            }
        }
        annotation_data = {
            '_id':rec._id, 
            'dbxref':{},
            'features': []
        }
        for f in (
            'PDBExt', 'RefSeq', 'IntAct', 'ChEMBL', 
            'DrugBank', 'KEGG', 'DisGeNET','MIM', 'GO',
            'InterPro', 'Pfam', 'PROSITE'):
            annotation_data['dbxref'][f] = []
        for field in rec.gene_name.split(';'):
            if not field:
                continue
            if field.find('=') == -1:
                continue
            lb, val = field.split('=', 1)
            if lb == 'Name':
                header_data['gn'] = val
            else:
                lb = lb.replace(' ','')
                header_data['gene_'+lb] = val
        
        if header_data['OX'] not in sources:
            sources[header_data['OX']] = header_data['OS']
            db_cols['sources'].insert_one({'_id': header_data['OX'], 'source': header_data['OS']})
            logging.info ("New source found: {}".format(header_data['OS']))
        header_data['source'] = header_data['OX']
        del header_data['OX']
        del header_data['OS']

        for xref in rec.cross_references:
            if xref[0] == 'Ensembl':
                header_data['dbxref']['Ensembl'].append(xref[1:])
            if xref[0] == 'PDB':
                header_data['dbxref']['PDB'].append(xref[1])
                annotation_data['dbxref']['PDBExt'].append(
                    {
                        'type': xref[2],
                        'id': xref[1],
                        'chains': xref[4],
                        'res': xref[3]
                    }
                )
            if xref[0] in ('RefSeq', 'GO'):
                annotation_data['dbxref'][xref[0]].append(xref[1:])
            if xref[0] in ('ChEMBL', 'KEGG', 'DisGeNET'):
                annotation_data['dbxref'][xref[0]].append({'id':xref[1]})
            if xref[0] in ('DrugBank', 'MIM', 'IntAct', 'InterPro', 'Pfam', 'PROSITE'):
                annotation_data['dbxref'][xref[0]].append(
                    {'id': xref[1], 'desc': xref[2]}
                )
        for feat in rec.features:
            ff = {
                    'type':feat.type,
                    'id':feat.id,
                    'desc':feat.qualifiers
            }
            if isinstance(feat.location.start, ExactPosition):
                ff['start'] = int(feat.location.start)
            else:
                ff['start'] = '?'
            if isinstance(feat.location.end, ExactPosition):
                ff['end'] = int(feat.location.end)
            else:
                ff['end'] = '?'
            annotation_data['features'].append(ff)
            
        sequence_data = {
            '_id':rec._id,
            'type' : 'protein',
            'origin' :'uniprot',
            'sequence': rec.sequence,
            'update': rec.sequence_update[0]
        }
        headBuff.append({'_id':rec._id},{'$set':header_data})
        seqBuff.append({'_id':rec._id},{'$set':sequence_data})
        annotBuff.append({'_id':rec._id},{'$set':annotation_data})
        headBuff.commit_data_if_full()
        seqBuff.commit_data_if_full()
        annotBuff.commit_data_if_full()
    
    headBuff.commit_any_data()
    seqBuff.commit_any_data()
    annotBuff.commit_any_data()
    db_cols['fileStamps'].update_one({'_id':file},{'$set':{'ts':f_mgr.tstamp}}, upsert=True)
    
logging.info('loadUniprotFull Done')

logging.info(headBuff.global_stats())

logging.info(seqBuff.global_stats())

logging.info(annotBuff.global_stats())


