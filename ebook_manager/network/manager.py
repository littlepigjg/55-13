from typing import List, Optional, Dict

from .douban import DoubanSource
from .openlibrary import OpenLibrarySource


class NetworkSourceManager:
    def __init__(self):
        self.douban = DoubanSource()
        self.openlibrary = OpenLibrarySource()

    def search(
        self, query: str, sources: Optional[List[str]] = None, max_results: int = 5
    ) -> List[Dict]:
        if sources is None:
            sources = ["douban", "openlibrary"]
        results = []
        if "douban" in sources:
            results.extend(self.douban.search_by_title(query, max_results))
        if "openlibrary" in sources:
            results.extend(self.openlibrary.search_by_title(query, max_results))
        return results[: max_results * 2]

    def search_by_isbn(self, isbn: str, sources: Optional[List[str]] = None) -> Optional[Dict]:
        if sources is None:
            sources = ["douban", "openlibrary"]
        if "douban" in sources:
            result = self.douban.search_by_isbn(isbn)
            if result:
                return result
        if "openlibrary" in sources:
            result = self.openlibrary.search_by_isbn(isbn)
            if result:
                return result
        return None
