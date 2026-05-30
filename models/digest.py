from dataclasses import dataclass, field
from models.company import Company
from models.job import Job


@dataclass
class CompanyDigest:
    company: Company
    matched: list[Job] = field(default_factory=list)
    kw_filtered: list[Job] = field(default_factory=list)
    llm_filtered: list[Job] = field(default_factory=list)


@dataclass
class DigestResult:
    date: str
    companies: list[CompanyDigest] = field(default_factory=list)
    unsupported_companies: list[Company] = field(default_factory=list)
