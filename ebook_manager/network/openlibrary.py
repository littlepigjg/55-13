import re
from typing import List, Optional, Dict


class OpenLibrarySource:
    SEARCH_URL = "https://openlibrary.org/search.json"

    def __init__(self):
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            self._session.headers.update({"User-Agent": "EbookManager/1.0"})
        return self._session

    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict]:
        try:
            session = self._get_session()
            params = {"title": title, "limit": max_results}
            resp = session.get(self.SEARCH_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            results = []
            for doc in data.get("docs", []):
                result = self._parse_ol_doc(doc)
                if result:
                    results.append(result)
            return results
        except Exception:
            return []

    def search_by_isbn(self, isbn: str) -> Optional[Dict]:
        clean_isbn = re.sub(r"[-\s]", "", isbn)
        try:
            session = self._get_session()
            url = f"https://openlibrary.org/isbn/{clean_isbn}.json"
            resp = session.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return self._parse_ol_isbn(data, clean_isbn)
        except Exception:
            pass
        return None

    def _parse_ol_doc(self, doc: dict) -> Optional[Dict]:
        try:
            authors = doc.get("author_name", [])
            author = ", ".join(authors) if isinstance(authors, list) else str(authors)
            publish_date = doc.get("first_publish_year", "")
            if publish_date:
                publish_date = str(publish_date)
            isbn_list = doc.get("isbn", [])
            isbn = isbn_list[0] if isbn_list else ""
            edition_keys = doc.get("edition_key", [])
            cover_url = ""
            if edition_keys:
                cover_url = f"https://covers.openlibrary.org/b/olid/{edition_keys[0]}/M.jpg"
            return {
                "title": doc.get("title", ""),
                "author": author,
                "publisher": ", ".join(doc.get("publisher", [])),
                "publish_date": publish_date,
                "isbn": isbn,
                "language": ", ".join(doc.get("language", [])),
                "source": "openlibrary",
                "cover_url": cover_url,
            }
        except Exception:
            return None

    def _parse_ol_isbn(self, data: dict, isbn: str) -> Optional[Dict]:
        try:
            title = data.get("title", "")
            authors = []
            for a in data.get("authors", []):
                if isinstance(a, dict):
                    authors.append(a.get("name", ""))
                else:
                    authors.append(str(a))
            publishers = data.get("publishers", [])
            publisher = publishers[0] if publishers else ""
            publish_date = data.get("publish_date", "")
            return {
                "title": title,
                "author": ", ".join(authors),
                "publisher": publisher if isinstance(publisher, str) else publisher.get("name", ""),
                "publish_date": publish_date,
                "isbn": isbn,
                "source": "openlibrary",
            }
        except Exception:
            return None
