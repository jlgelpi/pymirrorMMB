""" Manager for sequential text files """
import logging
import gzip
import os
import re


class FileMgr():
    """ Utility class to manage text files to be read sequentially """
    def __init__(self, file, ini_line=0, fin_line=0):
        self.fn = file
        file_stat = os.stat(self.fn)
        self.tstamp = int(file_stat.st_ctime)
        self.ini = ini_line
        self.fin = fin_line
        self.current_line = 0
        
    def check_new_stamp(self, tstamp_col):
        ''' Check if the file has a new time stamp compared to the stored one '''
        stored_tstamp = tstamp_col.find_one({'_id':self.fn})
        logging.info(f'File time stamp:   {self.tstamp:11.0f}')
        if stored_tstamp:
            logging.info(f"Stored time stamp: {stored_tstamp['ts']:11.0f}")
            if self.tstamp <= stored_tstamp['ts']:
                return False
        if not stored_tstamp:
            logging.info('Stored time stamp: None')
        return True
    
    def skip_lines_to(self, txt, match=False):
        ''' Skip lines until a line matches (or not matches) the given text '''
        header_lines = True
        for line in self:
        #    print(line)
            if match:
                header_lines = header_lines and line != txt
            else:
                header_lines = header_lines and not re.search(txt, line)
            if not header_lines:
                break

    def skip_lines_to_ini(self):
        ''' Skip lines until the initial line number '''
        if self.ini:
            for line in self:
                if self.current_line >= self.ini:
                    break
                    
    def skip_n_lines(self,n):
        ''' Skip n lines '''
        nlin=0
        for line in self:
            if nlin == n:
                break
            nlin += 1
    
    def open_file(self):
        ''' Open the file for reading '''
        try:
            if self.fn.find('.gz') != -1:
                self.fh_in = gzip.open(self.fn, 'rt')
            else:
                self.fh_in = open(self.fn, 'r') 
        except IOError as e:
            sys.exit(e.message)
        

    def close_file(self):
        ''' Close the file '''
        self.fh_in.close()

        
    def __next__(self):
        self.current_line += 1
        if self.fin and self.current_line > self.fin:
            raise StopIteration

        line = self.fh_in.__next__()
        if not isinstance(line, str):
            line = line.decode('ascii')
        return line.rstrip()

    def __iter__(self):
        return self

