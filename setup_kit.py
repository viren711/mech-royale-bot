"""Fetch the official, checksum-pinned development kit (not needed at runtime)."""
import hashlib
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parent
URL = 'https://www.joinbuilders.org/buildathon/tracks/builders/files/mechfight-kit.tar.gz'
SHA256 = '1758fe9125e193b268c6c1cffbf2c0ae96377214ab06d117412571c1523065ba'


def main():
    archive = ROOT / 'mechfight-kit.tar.gz'
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise SystemExit('Starter kit checksum changed; review the new kit before using it.')
    with tarfile.open(archive, 'r:gz') as tf:
        tf.extractall(ROOT, filter='data')
    print('Official kit ready in', ROOT / 'mechfight-kit')


if __name__ == '__main__':
    main()
