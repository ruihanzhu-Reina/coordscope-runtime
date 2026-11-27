"""Host-owned footprints and per-resource revision observations."""

import copy
import json
from dataclasses import dataclass

from .journal import canonical


@dataclass(frozen=True)
class Footprint:
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()

    def __post_init__(self):
        for field in ("reads", "writes"):
            value = getattr(self, field)
            if isinstance(value, str) or any(not isinstance(key, str) or not key for key in value):
                raise ValueError("Resource footprints require nonempty host resource keys.")
            object.__setattr__(self, field, tuple(sorted(set(value))))

    def to_document(self):
        return dict(reads=list(self.reads), writes=list(self.writes))


class ResourceTracker:
    def __init__(self, journal, revision=None):
        if revision is not None and not callable(revision):
            raise TypeError("Resource revision must be a host callback.")
        self.journal, self.revision = journal, revision

    def footprint(self, tool, arguments):
        if resolver := tool.get("resources"):
            footprint = resolver(copy.deepcopy(arguments))
            if not isinstance(footprint, Footprint):
                raise TypeError("Host resource resolver must return Footprint.")
        else:
            key = "domain:" + tool.get("resource_domain", tool["name"])
            footprint = Footprint(reads=(key,)) if tool["effect"] == "read" else Footprint(writes=(key,))
        if tool["effect"] != "read" and not footprint.writes:
            raise ValueError("An effect requires a declared write footprint.")
        if tool["effect"] == "read" and footprint.writes:
            raise ValueError("A read tool cannot declare a write footprint.")
        return footprint

    def capture(self, keys):
        stamps = {}
        for key, revision in self.journal.revisions(keys).items():
            validator = self.revision(key) if self.revision else None
            stamps[key] = dict(
                revision=revision, validator=json.loads(canonical(validator)), external=validator is not None
            )
        return stamps

    def validate(self, stamps):
        if not isinstance(stamps, dict):
            return False
        return canonical(self.capture(stamps)) == canonical(stamps)

    def bump(self, keys):
        self.journal.bump(keys)
