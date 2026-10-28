"""Private local key installation; never return key material to API clients."""
import os
from pathlib import Path
import re
import tempfile
from pokeldn.web.storage import StorageError

LIMIT = 256 * 1024


def keys_path():
    return Path(os.environ.get('PKMN_SBANK_KEYS', str(Path.home()/'.switch/prod.keys'))).expanduser().absolute()


def status():
    path = keys_path()
    return {'installed': path.is_file() and os.access(path, os.R_OK)}


def install(content):
    try:
        rows = {}
        for line in content.decode('utf-8-sig').splitlines():
            line = line.split('#', 1)[0].strip()
            if not line:
                continue
            name, value = (part.strip() for part in line.split('='))
            if not re.fullmatch('[a-z0-9_]+', name) or name in rows or not re.fullmatch('(?:[0-9a-fA-F]{2})+', value):
                raise ValueError
            rows[name] = value
        for name in ('master_key_00', 'aes_kek_generation_source', 'aes_key_generation_source'):
            if len(rows.get(name, '')) != 32:
                raise ValueError
    except (ValueError, UnicodeError):
        raise StorageError('Choose a valid prod.keys file with the required LDN keys. Existing keys were kept.', 422) from None
    if not content or len(content) > LIMIT:
        raise StorageError('The keys upload limit is 256 KiB.', 413)
    path = keys_path()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise StorageError('The configured keys location must not use symbolic links.', 422)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.prod-keys-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            # Normalize comments/BOM for compatibility with upstream's parser.
            out.write((''.join(f'{name} = {value}\n' for name, value in rows.items())).encode())
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return status()
