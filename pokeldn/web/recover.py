"""Recover a downloaded Bank ZIP with the website server stopped."""
import argparse
import os
from pathlib import Path
from pokeldn.web.storage import BankStore, StorageError


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('backup',type=Path)
    parser.add_argument('--data-dir',type=Path,default=Path(os.environ.get('POKELDN_DATA',str(Path.home()/'.local/share/pkmn-sbank'))))
    args=parser.parse_args()
    os.umask(0o077)
    try:
        BankStore(args.data_dir/'web-bank').restore_archive(args.backup)
    except StorageError as error:
        parser.exit(1,str(error)+'\n')
    print('Backup verified and committed as a new snapshot. You can restart the website.')


if __name__=='__main__':
    main()
