
import logging
import sys

from pymongo import DeleteOne, UpdateOne, UpdateMany
from pymongo.errors import BulkWriteError

CTS = {
    'UPDATE': 0,
    'UPSERT': 1,
    'DELETE': 2,
    'INSERT': 3
}

OP_LABELS = ['update', 'upsert', 'delete', 'insert']

class MongoDBBulkWrite():
    ''' Class to handle bulk write operations to MongoDB '''

    def __init__(self, collection, mode, size):
        self.collection = collection
        self.desc = OP_LABELS[mode]
        self.mode = mode
        self.length = size
        self.data = []
        self.ibuff = 0
        self.total = 0
        self.removed = 0
        self.upserted = 0
        self.modified = 0
        self.inserted = 0

    def clean(self):
        ''' Clean the internal buffer '''
        self.data = []
        self.ibuff = 0

    def append(self, id, val, ser_id=None):
        ''' Append a new operation to the buffer '''
        self.data.append({
            'id': id,
            'val': val,
            'ser_id': ser_id
        })
        self.ibuff += 1

    def full(self):
        ''' Check if the buffer is full '''
        return self.ibuff >= self.length

    def reset(self):
        ''' Reset the internal counters and buffer '''
        self.clean()
        self.total = 0

    def commit_data(self, if_full=True, many=False):
        ''' Commit the data in the buffer to the database '''
        if not if_full or self.full():
            if self.ibuff:
                if self.mode == CTS['INSERT']:
                    buffer = []
                    for item in self.data:
                        buffer.append(item['val'])
                        self.collection.insert_many(buffer)
                    log = f'Committing {self.ibuff:7.0f} ops. ({self.total:8.0f}) to {self.collection.name:15s}:'
                    log += f'{len(buffer):7.0f} inserted'
                    logging.info(log)
                    self.inserted += len(buffer)
                else:
                    bulk = []
                    last_id = ''
                    for item in self.data:
                        if self.mode == CTS['UPSERT']:
                            bulk.append(UpdateOne(item['id'], item['val'], upsert=True))
                        elif self.mode == CTS['DELETE']:
                            bulk.append(DeleteOne(item['id']))
                        else:
                            if many:
                                bulk.append(UpdateMany(item['id'], item['val']))
                            else:
                                bulk.append(UpdateOne(item['id'], item['val']))
                        if item['ser_id']:
                            last_id = item['ser_id']
                        elif '_id' in item['id']:
                            last_id = item['id']['_id']
                    try:
                        hres = self.collection.bulk_write(bulk, ordered=False)
                    except BulkWriteError as bwe:
                        logging.error(bwe.details)
                        sys.exit()

                    self.total += self.ibuff
                    log = f'Committing {self.ibuff:7} ops. ({self.total:8}) to {self.collection.name:15}:'
                    log += f'{hres.matched_count:7} matched, {hres.deleted_count:7} removed, {hres.upserted_count:7} upserted, {hres.modified_count:7} modified'
                    if last_id:
                        log += f" (Last processed Id: {last_id})"
                    logging.info(log)
                    self.removed += hres.deleted_count
                    self.upserted += hres.upserted_count
                    self.modified += hres.modified_count
                    self.clean()

    def commit_data_if_full(self, many=False):
        ''' Commit data if the buffer is full '''
        self.commit_data(True, many)

    def commit_any_data(self, many=False):
        ''' Commit any data in the buffer '''
        self.commit_data(False, many)

    def global_stats(self):
        ''' Return a string with the global statistics '''        
        log = f"{self.collection.name:10} ({OP_LABELS[self.mode]:6}) {self.total:8} ops, "
        log += f"{self.removed:7} removed, {self.upserted:7} upserted, {self.modified:7} modified"
        return log
