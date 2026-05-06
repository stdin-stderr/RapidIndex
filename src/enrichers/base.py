from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.parsing.title_parser import ParsedTitle
from src.storage.models import Release


@dataclass
class EnrichmentResult:
    matched: bool
    score: float
    external_id: str
    metadata: dict = field(default_factory=dict)


class Enricher(ABC):
    @abstractmethod
    async def enrich(self, release: Release, parsed: ParsedTitle) -> EnrichmentResult: ...
