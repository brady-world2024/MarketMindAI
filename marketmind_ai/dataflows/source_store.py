"""Immutable, content-addressed acquisition snapshots in application storage."""
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile

from .results import safe_json
from .source_policy import POLICY_VERSION, PROCESSING_VERSION
from .source_records import ResearchDataSnapshot, SNAPSHOT_FORMAT_VERSION


class SnapshotIntegrityError(ValueError):
    pass


def canonical_json(value) -> bytes:
    return json.dumps(safe_json(value), sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def snapshot_fingerprint(snapshot: ResearchDataSnapshot) -> str:
    return sha256(canonical_json(snapshot.to_dict())).hexdigest()


class SourceStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.blobs = self.root / 'blobs'
        self.snapshots = self.root / 'snapshots'
        self.blobs.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.snapshots.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def _identifier(value: str, length: int) -> str:
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{' + str(length) + r'}', value):
            raise SnapshotIntegrityError('The saved source identifier is invalid.')
        return value

    @staticmethod
    def _write_once(path: Path, body: bytes):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
                temporary = Path(target.name)
                target.write(body)
                target.flush()
                os.fsync(target.fileno())
            try:
                # The complete file appears atomically; an existing version is
                # never overwritten, including when two requests race.
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != body:
                    raise SnapshotIntegrityError('A saved source version cannot be overwritten.') from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def write_blob(self, body) -> str:
        sanitized = safe_json(body)
        content = sanitized.encode('utf-8') if isinstance(sanitized, str) else canonical_json(sanitized)
        digest = sha256(content).hexdigest()
        self._write_once(self.blobs / digest, content)
        return digest

    def read_blob(self, digest: str) -> str:
        identifier = self._identifier(digest, 64)
        try:
            body = (self.blobs / identifier).read_bytes()
            if sha256(body).hexdigest() != identifier:
                raise SnapshotIntegrityError('Saved source content failed its fingerprint check.')
            return body.decode('utf-8')
        except (OSError, UnicodeError):
            raise SnapshotIntegrityError('Saved source content is unavailable or invalid.') from None

    @staticmethod
    def _versions(snapshot: ResearchDataSnapshot):
        if (snapshot.format_version != SNAPSHOT_FORMAT_VERSION or snapshot.policy_version != POLICY_VERSION
                or snapshot.processing_version != PROCESSING_VERSION):
            raise SnapshotIntegrityError('The saved source version is not supported.')

    def save(self, snapshot: ResearchDataSnapshot) -> str:
        self._versions(snapshot)
        for record in snapshot.records:
            if record.raw_sha256 is not None:
                self.read_blob(record.raw_sha256)
        digest = snapshot_fingerprint(snapshot)
        envelope = canonical_json({'snapshot': snapshot.to_dict(), 'sha256': digest})
        identifier = self._identifier(snapshot.snapshot_id, 32)
        self._write_once(self.snapshots / f'{identifier}.json', envelope)
        return digest

    def load(self, snapshot_id: str) -> ResearchDataSnapshot:
        identifier = self._identifier(snapshot_id, 32)
        try:
            envelope = json.loads((self.snapshots / f'{identifier}.json').read_text(encoding='utf-8'))
            if set(envelope) != {'snapshot', 'sha256'}:
                raise ValueError
            if sha256(canonical_json(envelope['snapshot'])).hexdigest() != envelope['sha256']:
                raise SnapshotIntegrityError('The source snapshot failed its fingerprint check.')
            snapshot = ResearchDataSnapshot.model_validate(envelope['snapshot'])
            if snapshot.snapshot_id != identifier:
                raise SnapshotIntegrityError('The saved source identity does not match.')
            self._versions(snapshot)
            for record in snapshot.records:
                if record.raw_sha256 is not None:
                    self.read_blob(record.raw_sha256)
            return snapshot
        except SnapshotIntegrityError:
            raise
        except (OSError, ValueError, TypeError, KeyError):
            raise SnapshotIntegrityError('The source snapshot is unavailable or invalid.') from None
