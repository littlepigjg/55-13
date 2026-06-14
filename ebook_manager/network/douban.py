import re
from typing import List, Optional, Dict


class DoubanSource:
    SEARCH_URL = "https://search.douban.com/book/subject_search"
    SUGGEST_URL = "https://book.douban.com/j/subject_suggest"
    SUBJECT_URL = "https://book.douban.com/subject/"

    def __init__(self):
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests

            self._session = requests.Session()
            self._session.headers.update(
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }
            )
        return self._session

    def search_by_title(self, title: str, max_results: int = 5) -> List[Dict]:
        try:
            results = self._search_via_suggest(title, max_results)
            if results:
                return results[:max_results]
        except Exception:
            pass
        try:
            return self._search_via_html(title, max_results)
        except Exception:
            return []

    def search_by_isbn(self, isbn: str) -> Optional[Dict]:
        clean_isbn = re.sub(r"[-\s]", "", isbn)
        try:
            results = self._search_via_suggest(clean_isbn, 1)
            if results:
                return results[0]
        except Exception:
            pass
        try:
            results = self._search_via_html(clean_isbn, 1)
            if results:
                return results[0]
        except Exception:
            pass
        return None

    def get_book_detail(self, subject_id: str) -> Optional[Dict]:
        try:
            from bs4 import BeautifulSoup

            session = self._get_session()
            url = f"{self.SUBJECT_URL}{subject_id}/"
            resp = session.get(url, timeout=10)
            resp.raise_for_status()
            return self._parse_detail_html(resp.text, subject_id)
        except Exception:
            pass
        return None

    def _search_via_suggest(self, query: str, max_results: int) -> List[Dict]:
        import json

        session = self._get_session()
        params = {"q": query}
        resp = session.get(self.SUGGEST_URL, params=params, timeout=10)
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            return []
        results = []
        for item in data[:max_results]:
            if not isinstance(item, dict):
                continue
            result = {
                "title": item.get("title", ""),
                "author": self._clean_author(item.get("author_name", "")),
                "publisher": item.get("publisher", ""),
                "publish_date": item.get("year", ""),
                "source": "douban",
                "subject_id": str(item.get("id", "")),
                "cover_url": item.get("pic", ""),
                "source_url": item.get("url", ""),
            }
            if result["title"]:
                results.append(result)
        return results

    def _search_via_html(self, query: str, max_results: int) -> List[Dict]:
        from bs4 import BeautifulSoup

        session = self._get_session()
        params = {"search_text": query, "cat": "1001"}
        resp = session.get(self.SEARCH_URL, params=params, timeout=15)
        resp.raise_for_status()
        return self._parse_search_html(resp.text, max_results)

    def _parse_search_html(self, html: str, max_results: int) -> List[Dict]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results = []

        items = soup.select("div.item-root")
        if not items:
            items = soup.select("div.subject-list div.subject-item")
        if not items:
            items = soup.select("#content div.item")

        for item in items[:max_results]:
            result = self._parse_item_element(item)
            if result and result.get("title"):
                results.append(result)

        if not results:
            results = self._try_extract_from_script(soup, max_results)

        return results

    def _parse_item_element(self, item) -> Optional[Dict]:
        try:
            title = ""
            link = ""
            title_elem = item.select_one("a.title-text")
            if title_elem:
                title = title_elem.get_text(strip=True)
                link = title_elem.get("href", "")
            if not title_elem:
                title_elem = item.select_one("a[onclick]")
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    link = title_elem.get("href", "")
            if not title_elem:
                title_elem = item.select_one("h2 a")
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    link = title_elem.get("href", "")
            if not title_elem:
                a_tag = item.select_one("a")
                if a_tag:
                    title = a_tag.get_text(strip=True)
                    link = a_tag.get("href", "")

            subject_id = ""
            if link:
                id_match = re.search(r"subject/(\d+)", link)
                if id_match:
                    subject_id = id_match.group(1)

            meta_text = ""
            meta_elem = item.select_one("div.meta")
            if meta_elem:
                meta_text = meta_elem.get_text(strip=True)
            if not meta_elem:
                pub_elem = item.select_one("div.pub")
                if pub_elem:
                    meta_text = pub_elem.get_text(strip=True)

            author = ""
            publisher = ""
            publish_date = ""
            if meta_text:
                parts = [p.strip() for p in meta_text.split("/") if p.strip()]
                for part in parts:
                    if re.match(r"^\d{4}", part):
                        publish_date = part
                    elif any(k in part for k in ["出版社", "出版", "Publish"]):
                        publisher = part
                    elif not author:
                        author = part

            rating = ""
            rating_elem = item.select_one("span.rating_nums")
            if rating_elem:
                rating = rating_elem.get_text(strip=True)

            cover_url = ""
            cover_elem = item.select_one("img")
            if cover_elem:
                cover_url = cover_elem.get("src", "") or cover_elem.get("data-src", "")

            return {
                "title": title,
                "author": author,
                "publisher": publisher,
                "publish_date": publish_date,
                "source": "douban",
                "subject_id": subject_id,
                "source_url": link,
                "cover_url": cover_url,
                "rating": rating,
            }
        except Exception:
            return None

    def _try_extract_from_script(self, soup, max_results: int) -> List[Dict]:
        results = []
        for script in soup.find_all("script"):
            text = script.string or ""
            pattern = r'"title"\s*:\s*"([^"]+)"'
            titles = re.findall(pattern, text)
            if not titles:
                pattern = r'"name"\s*:\s*"([^"]+)"'
                titles = re.findall(pattern, text)
            if titles:
                ids = re.findall(r'"id"\s*:\s*"(\d+)"', text)
                urls = re.findall(r'"url"\s*:\s*"([^"]+subject/[^"]*)"', text)
                authors = re.findall(r'"author"\s*:\s*\[?"([^"]*)"', text)
                publishers = re.findall(r'"publisher"\s*:\s*\[?"([^"]*)"', text)
                for i, t in enumerate(titles[:max_results]):
                    result = {
                        "title": t,
                        "author": authors[i] if i < len(authors) else "",
                        "publisher": publishers[i] if i < len(publishers) else "",
                        "publish_date": "",
                        "source": "douban",
                        "subject_id": ids[i] if i < len(ids) else "",
                        "source_url": urls[i] if i < len(urls) else "",
                    }
                    if result["title"]:
                        results.append(result)
                if results:
                    break
        return results

    def _parse_detail_html(self, html: str, subject_id: str) -> Optional[Dict]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        result = {"source": "douban", "subject_id": subject_id}

        title_elem = soup.select_one("h1 span")
        if title_elem:
            result["title"] = title_elem.get_text(strip=True)
        else:
            title_elem = soup.select_one("span[property='v:itemreviewed']")
            result["title"] = title_elem.get_text(strip=True) if title_elem else ""

        info_div = soup.select_one("div#info")
        if info_div:
            text = info_div.get_text()
            result["author"] = self._extract_field(text, "作者")
            result["publisher"] = self._extract_field(text, "出版社")
            result["isbn"] = self._extract_field(text, "ISBN")
            result["publish_date"] = self._extract_field(text, "出版年")

        desc_elem = soup.select_one("div.intro")
        if desc_elem:
            result["description"] = desc_elem.get_text(strip=True)[:300]

        return result if result.get("title") else None

    @staticmethod
    def _extract_field(text: str, label: str) -> str:
        pattern = rf"{label}\s*[:：]\s*([^\n]+)"
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        return ""

    @staticmethod
    def _clean_author(author: str) -> str:
        author = re.sub(r"[\[\]]", "", author)
        author = re.sub(r"\s*/\s*", ", ", author)
        return author.strip()
