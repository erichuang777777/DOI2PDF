"""Small live corpus for user-run acceptance checks; no mock responses."""

from __future__ import annotations

from typing import Any


LIVE_CORPUS: tuple[dict[str, Any], ...] = (
    {
        "doi": "10.1016/j.ipm.2025.104216",
        "publisher": "Elsevier",
        "title": "A survey on biomedical automatic text summarization with large language models",
        "source_url": "https://www.sciencedirect.com/science/article/pii/S0306457325001578",
        "access_class": "subscription",
        "baseline": "not_retrieved_without_access",
    },
    {
        "doi": "10.1016/j.colsurfa.2025.138224",
        "publisher": "Elsevier",
        "title": "Hyaluronic acid-modified hollow MnO2-loaded IR780 smart theranostic platform",
        "source_url": "https://www.sciencedirect.com/science/article/abs/pii/S0927775725021272",
        "access_class": "subscription",
        "baseline": "not_retrieved_without_access",
    },
    {
        "doi": "10.1111/ans.17268",
        "publisher": "Wiley",
        "title": "Art and anatomy in the renaissance: are the lessons still relevant today",
        "source_url": "https://onlinelibrary.wiley.com/doi/abs/10.1111/ans.17268",
        "access_class": "subscription",
        "baseline": "not_retrieved_without_access",
    },
    {
        "doi": "10.1002/hed.27891",
        "publisher": "Wiley / PMC",
        "title": "Surgical outcomes of profunda artery perforator flap in head and neck reconstruction",
        "source_url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC11635749/",
        "access_class": "known_oa_discovery_gap",
        "baseline": "not_retrieved_without_access",
    },
    {
        "doi": "10.1038/s44161-024-00596-9",
        "publisher": "Nature Portfolio",
        "title": "TRPM7 channel activity promotes the pathogenesis of abdominal aortic aneurysms",
        "source_url": "https://www.nature.com/articles/s44161-024-00596-9",
        "access_class": "subscription",
        "baseline": "not_retrieved_without_access",
    },
    {
        "doi": "10.1056/NEJMoa2404512",
        "publisher": "New England Journal of Medicine",
        "title": "Nonoperative Management of Mismatch Repair-Deficient Tumors",
        "source_url": "https://www.nejm.org/doi/10.1056/NEJMoa2404512",
        "access_class": "subscription",
        "baseline": "not_retrieved_without_access",
    },
    {
        "doi": "10.1056/NEJMoa2600157",
        "publisher": "New England Journal of Medicine",
        "title": "Continuous or Fixed-Duration Maintenance Therapy in Multiple Myeloma",
        "source_url": "https://www.nejm.org/doi/pdf/10.1056/NEJMoa2600157",
        "access_class": "subscription",
        "baseline": "not_retrieved_without_access",
    },
    {
        "doi": "10.1093/eurheartj/ehaf429",
        "publisher": "Oxford University Press",
        "title": "Lessons from coronary physiology: primum non nocere",
        "source_url": "https://academic.oup.com/eurheartj/article/46/39/3860/8238355",
        "access_class": "subscription",
        "baseline": "not_retrieved_without_access",
    },
)


def corpus(publisher: str | None = None) -> list[dict[str, Any]]:
    rows = [dict(item) for item in LIVE_CORPUS]
    if publisher:
        needle = publisher.casefold()
        rows = [item for item in rows if needle in item["publisher"].casefold()]
    return rows
