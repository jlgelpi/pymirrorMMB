import logging

def print_progress(prefix, nids, ntot, inc):
    """ Print progress information """
    ntot = max(1, ntot)
    if nids%inc == 0:
        logging.info("{} {:8}/{:8} {:5.1f}%".format(prefix, nids, ntot, (nids*100./ntot)))


def get_id(fasta_header):
    ''' Extract unique identifier from a FASTA header line '''
    ids, desc = fasta_header.split(' ', 1)
    if '|' in ids:
        _, uniq_id, _ = ids.split('|', 2)
        return uniq_id
    return ''
