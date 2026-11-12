#!/usr/bin/env python3
#encoding: UTF-8

"""Load files into MongoDB GridFS with timestamp/MD5 comparison."""

import argparse
import hashlib
import logging
import os
import sys
from datetime import datetime



from mmb_data.mongo_db_connect import MongoDB

AUTH = True

class LocalFile(object):
    """Class to represent a local file with metadata."""
    def __init__(self, filepath, use_md5=False):
        self.filepath = filepath
        self.filename = os.path.basename(filepath)
        self.mtime = self._get_file_mtime()
        self.md5 = self.calculate_md5() if use_md5 else None

    def calculate_md5(self):
        """Calculate MD5 hash of a file."""
        md5_hash = hashlib.md5()
        try:
            with open(self.filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except IOError as e:
            logging.error(f"Error calculating MD5 for {self.filepath}: {e}")
            return None

    def _get_file_mtime(self):
        """Get file modification time as datetime object (ISODate format)."""
        try:
            stat_info = os.stat(self.filepath)
            mtime = datetime.fromtimestamp(stat_info.st_mtime)
            return mtime
        except OSError as e:
            logging.error(f"Error getting mtime for {self.filepath}: {e}")
        return None


def get_gridfs_files(grid, ext_filter=None):
    """Get dict of files currently in GridFS with their metadata."""
    files_db = {}

    try:
        query = {}
        if ext_filter:
            query = {'filename': {'$regex': f"{ext_filter}$"}}
        files_cursor = grid.find(query)
    except Exception as e:
        logging.error(f"Error querying GridFS: {e}")
        return files_db

    for file_doc in files_cursor:
        filename = file_doc.filename
        if not filename:
            continue

        # Filter by extension if specified
        if ext_filter and not filename.endswith(f".{ext_filter}"):
            continue

        files_db[file_doc.filename] = file_doc

    return files_db


def get_directory_files(directory, ext_filter=None, use_md5=False, file_distribution="divided"):
    """Get list of files in directory, optionally filtered by extension."""
    files_dir = {}
    try:
        if file_distribution == "all":
            for fn in os.listdir(directory):
                filepath = os.path.join(directory, fn)
                if not os.path.isfile(filepath) or ext_filter and not fn.endswith(f".{ext_filter}"):
                    continue
                file = LocalFile(filepath, use_md5=use_md5)
                files_dir[file.filename] = file
        elif file_distribution == "divided":
            for root, _, files in os.walk(directory):
                for fn in files:
                    if ext_filter and not fn.endswith(f".{ext_filter}"):
                        continue
                    file=LocalFile(os.path.join(root, fn), use_md5=use_md5)
                    files_dir[file.filename] = file
        else:
            logging.error(f"ERROR: Invalid file distribution type {file_distribution}")
            return None
    except OSError as e:
        logging.error(f"Error reading directory {directory}: {e}")

    return files_dir

def delete_missing_files(grid, files_db, files_dir, dry_run=False):
    """Delete files from GridFS that are no longer in the directory."""
    ndel = 0
    to_delete = [db_file for db_file in files_db if db_file not in files_dir]
    for db_file in to_delete:
        ndel += 1
        if not dry_run:
            try:
                # Find and delete the file by filename
                for file_doc in grid.find({"filename": db_file}):
                    grid.delete(file_doc._id)
            except Exception as e:
                logging.error(f"Error deleting {db_file}: {e}")
            del files_db[db_file]
        else:
            logging.info(f"[DRY-RUN] Would delete {db_file}")
    return ndel

def check_file_update(local_file, files_db, use_md5):
    try:
        if local_file.filename not in files_db:
            return "add"
        if use_md5:
            if local_file.md5 == files_db[local_file.filename].metadata.get("md5"):
                return None
            else:
                return "update"
        else:
            if local_file.mtime > files_db[local_file.filename].uploadDate:
                return "update"
    except Exception as e:
        logging.error(f"Error checking file {local_file.filename}: {e}")

    return None

def sync_files(grid, files_db, files_dir, directory, load_all=False, use_md5=False, dry_run=False):
    """Add or update files in GridFS based on timestamp or MD5 comparison."""
    nadd = 0
    nupd = 0
    ninp = 0
    logging.info(f"Syncing {len(files_dir)} files from {directory} to GridFS...")
    for filename, file_data in files_dir.items():
        todo = check_file_update(files_dir[filename], files_db, use_md5) if not load_all else "update"
        if todo is None:
            continue
        # Read file content for upload
        with open(file_data.filepath, "rb") as fh:
            logging.debug(f"Processing {filename}: action={todo}, mtime={file_data.mtime}, md5={file_data.md5}")
            if file_data.md5 is None:
                file_data.md5 = file_data.calculate_md5()
            if todo == "update":
                if not dry_run:
                # Delete old copies file by _id
                    for file_doc in grid.find({"filename": filename}):
                        grid.delete(file_doc._id)
                    grid.upload_from_stream(
                        filename, fh,
                        metadata = {"md5": file_data.md5}
                    )
                else:
                    logging.info(f"[DRY-RUN] Would update {filename}")
                nupd += 1
            else:
                if not dry_run:
                    grid.upload_from_stream(
                        filename, fh,
                        metadata = {"md5": file_data.md5}
                    )
                else:
                    logging.info(f"[DRY-RUN] Would add {filename}")
                    files_db[filename] = {
                        "filename": filename,
                        "uploadDate": file_data.mtime,
                        "metadata": {"md5": file_data.md5}
                    }
                nadd += 1

    return nadd, nupd


def main():
    """Parse arguments and sync files to GridFS."""
    cmd = argparse.ArgumentParser(
        description="Load files into MongoDB GridFS with timestamp/MD5 comparison"
    )
    cmd.add_argument("--ext", help="Filter files by extension", required=True)
    cmd.add_argument("--del", dest="delete_missing", action="store_true",
                     help="Delete files from GridFS if not in directory (requires --ext)")
    cmd.add_argument("--md5", action="store_true", help="Use MD5 checksums for comparison")
    cmd.add_argument("--all", dest="load_all", action="store_true",
                     help="Reload all files regardless of timestamps or checksums")
    cmd.add_argument("--host", default="localhost", help="MongoDB host (default: localhost)")
    cmd.add_argument("--database", default="FlexPortal", help="MongoDB database (default: FlexPortal)")
    cmd.add_argument("--bucket", required=True, help="GridFS bucket name (required)")
    cmd.add_argument("--debug", action="store_true", help="Debug logging")
    cmd.add_argument("--file_distribution", default="divided",
                     help="Type of file distribution (all|divided), default: divided)"
                    )
    cmd.add_argument("--dry_run", action="store_true",
                     help="Perform analysis without modifying files in GridFS")
    cmd.add_argument("directory", help="Root directory containing files to load")
    args = cmd.parse_args()

    logging.basicConfig(
        stream=sys.stdout,
        format="[%(asctime)s] %(levelname)s %(message)s",
        datefmt="%Y-%m-%d|%H:%M:%S",
    )
    logging.getLogger().setLevel(10 if args.debug else 20)

    # Validate arguments
    if args.delete_missing and not args.ext:
        logging.error("ERROR: --del option requires --ext")
        return 1

    if not os.path.isdir(args.directory):
        logging.error(f"ERROR: directory {args.directory} does not exist")
        return 1

    logging.info(f"Loading {args.bucket}")

    # Connect to MongoDB
    db_lnk = MongoDB(args.host, args.database, False, AUTH)
    db_lnk.connect_db()
    grid = db_lnk.get_gfs(args.bucket)

    if grid is None:
        logging.error("ERROR: Failed to connect to GridFS")
        return 1
    if args.ext:
        logging.info(f"Filtering for files with {args.ext} extension")

    logging.info("Getting database entries...")
    files_db = get_gridfs_files(grid, args.ext)
    logging.info(f"{len(files_db)} found")

    # Get directory file list
    logging.info(f"Getting input file list from {args.directory} as {args.file_distribution}...")
    if args.md5:
        logging.info("Using MD5 checksums for comparison")
    files_dir = get_directory_files(args.directory, ext_filter=args.ext, file_distribution=args.file_distribution, use_md5=args.md5)
    ndir_files = len(files_dir)
    logging.info(f"{ndir_files} found")

    nadd = 0
    nupd = 0
    ndel = 0

    # Delete missing files if requested
    if args.delete_missing:
        if ndir_files:
            ndel = delete_missing_files(grid, files_db, files_dir, args.dry_run)
            logging.info(f"{ndel} files deleted from GridFS")
        else:
            logging.error("ERROR: source directory is empty, exiting")
            db_lnk.close()
            return 1

    # Sync files
    nadd, nupd = sync_files(grid, files_db, files_dir, args.directory, args.load_all, args.md5, args.dry_run)
    if args.dry_run:
        logging.info(f"[DRY-RUN] {args.bucket} analysis complete: Would add {nadd}, update {nupd}, delete {ndel}")
    else:
        logging.info(f"{args.bucket} completed: Added {nadd} Updated {nupd} Deleted {ndel}")

    db_lnk.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
