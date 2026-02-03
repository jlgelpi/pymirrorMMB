# package mongo_db_connect;
#
## Based on generic access auth, TODO adapt to per database auth
## Defaults to mmb

import sys
import os
import yaml

from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from gridfs import GridFS

CONNECT_TIMEOUT_MS = 20000
SERVER_SELECTION_TIMEOUT_MS = 2000

def _load_secrets():
    """Load credentials from secrets.yaml file"""
    secrets_file = os.path.join(os.path.dirname(__file__), 'secrets.yaml')
    if not os.path.exists(secrets_file):
        raise FileNotFoundError(f"Secrets file not found: {secrets_file}")
    with open(secrets_file, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

class MongoDB():
    ''' Class to handle MongoDB connection '''
    def __init__(self, host, db, read_only, auth=True, wconcern=1):
        secrets = _load_secrets()
        self.credentials = secrets['credentials']
        self.auth_db = secrets['auth_db']
        self.host = host
        self.db = db
        self.read_only = read_only
        self.auth = auth
        self.wconcern = wconcern
        self._set_uri()

        self.connected = False
        self.client = None

    def set_auth(self, user, passw, auth_db):
        ''' Set authentication credentials '''
        if self.read_only:
            self.credentials['ROUser'] = user
            self.credentials['ROPwd'] = passw
        else:
            self.credentials['RWUser'] = user
            self.credentials['RWPwd'] = passw
        self.auth_db = auth_db

    def _set_uri(self):
        self.uri = 'mongodb://'
        if self.auth:
            if self.read_only:
                self.uri += f'{self.credentials["ROUser"]}:{self.credentials["ROPwd"]}@{self.host}/{self.auth_db}'
            else:
                self.uri += f'{self.credentials["RWUser"]}:{self.credentials["RWPwd"]}@{self.host}/{self.auth_db}'
        else:
            self.uri += self.host
#        print(self.uri)

    def connect_db(self):
        ''' Connect to the database '''
        if not self.connected:
            self._db_connect()

    def get_collections(self, cols):
        ''' Get multiple collections '''
        if not self.connected:
            self._db_connect()
        dbs = {}
        for c in cols:
            dbs[c] = self.db.get_collection(c)
        return dbs

    def get_gfs(self, col_name='fs'):
        ''' Get GridFS collection '''
        return GridFS(self.db, col_name, disable_md5=True)

    def _db_connect(self):
        if not self.uri:
            self._set_uri()
        try:
            self.client = MongoClient(
                self.uri,
                connectTimeoutMS=CONNECT_TIMEOUT_MS,
                serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
                w=self.wconcern
            )
            self.db = self.client.get_database(self.db)
            self.connected = True
        except ConnectionFailure:
            sys.exit("Error connecting DB")

    def close(self):
        ''' Close the database connection '''
        if self.connected:
            self.client.close()
            self.connected = False
