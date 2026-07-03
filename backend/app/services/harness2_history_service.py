from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import re
import shutil
import socket
import uuid
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from app.schemas.harness2 import (
    Harness2BuildRequest,
    Harness2BuildResponse,
    Harness2Evaluation,
    Harness2HistoryResponse,
    Harness2ReportItem,
    Harness2TrendPoint,
    Harness2UploadBuildRequest,
)
from phase1_data_pipeline.pdf_to_markdown import convert_pdf_to_markdown
from phase2_llm_engine.llm_client import query_llm
from phase2_llm_engine.trackb_harnesses.harness1.h1_1 import build_retrieval_context


_LINK_RE = re.compile(r'href=[\"\']([^\"\']+)[\"\']', re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")
_DATE_RE = re.compile(r"(20\d{2})[-_/]?(0[1-9]|1[0-2])[-_/]?(0[1-9]|[12]\d|3[01])")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


@dataclass
class _Candidate:
    url: str
    title: str
    score: int


class Harness2HistoryService:
    def __init__(self) -> None:
        self.timeout = 20
        self.max_download_bytes = 50 * 1024 * 1024
        self.http_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[3]

    def _output_root(self) -> Path:
        root = self._repo_root() / "phase4_evaluation" / "results" / "harness2_history"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _coerce_datetime(self, value: object, fallback_path: Path) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                parsed = None
            if parsed is not None:
                if parsed.tzinfo is None:
                    return parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc)
        try:
            return datetime.fromtimestamp(fallback_path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)

    def _read_json(self, path: Path) -> Dict[str, object]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _safe_read_text(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    def _text_mirror_url(self, url: str) -> str:
        parsed = urlparse(url)
        return f"https://r.jina.ai/http://{parsed.netloc}{parsed.path}"

    def _fetch_text_via_mirror(self, url: str) -> str:
        mirror_url = self._text_mirror_url(url)
        response = requests.get(
            mirror_url,
            timeout=self.timeout,
            headers={"User-Agent": self.http_headers["User-Agent"]},
            allow_redirects=True,
        )
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text

    def _fallback_report_items(self, run_dir: Path) -> List[Harness2ReportItem]:
        reports: List[Harness2ReportItem] = []
        candidate_dirs = [run_dir / "internal_reports", run_dir / "markdown"]
        for candidate_dir in candidate_dirs:
            if not candidate_dir.exists():
                continue
            for file_path in sorted(candidate_dir.glob("*.md")):
                title = file_path.stem.replace("_", " ").strip() or file_path.stem
                reports.append(
                    Harness2ReportItem(
                        title=title,
                        source_url="",
                        pdf_path=str((run_dir / "pdf" / f"{file_path.stem}.pdf").resolve()),
                        markdown_path=str(file_path.resolve()),
                        internal_report_path=str(file_path.resolve()),
                        report_date=None,
                        predicted_trend="flat",
                        actual_trend="unknown",
                        trend_correct=None,
                        price_start=None,
                        price_end=None,
                        summary="",
                        overview="",
                        further_direction="",
                        rating=0.0,
                    )
                )
        return reports

    def _build_response_from_run_dir(self, run_dir: Path) -> Optional[Harness2BuildResponse]:
        manifest_path = run_dir / "manifest.json"
        manifest = self._read_json(manifest_path) if manifest_path.exists() else {}

        if manifest:
            try:
                raw_reports = manifest.get("reports", [])
                raw_trend_points = manifest.get("trend_points", [])
                raw_evaluation = manifest.get("evaluation", {})
                response = Harness2BuildResponse(
                    run_id=str(manifest.get("run_id") or run_dir.name),
                    created_at=self._coerce_datetime(manifest.get("created_at"), run_dir),
                    seed_url=str(manifest.get("seed_url") or ""),
                    resolved_root_link=str(manifest.get("resolved_root_link") or manifest.get("seed_url") or ""),
                    symbol=str(manifest.get("symbol") or ""),
                    output_dir=str(run_dir),
                    reports=[Harness2ReportItem.model_validate(item) for item in raw_reports],
                    trend_points=[Harness2TrendPoint.model_validate(item) for item in raw_trend_points],
                    evaluation=Harness2Evaluation.model_validate(raw_evaluation or {}),
                    notes=[str(note) for note in manifest.get("notes", []) if str(note).strip()],
                    download_script_path=str(
                        manifest.get("download_script_path") or (run_dir / "scripts" / "secure_download_reports.py")
                    ),
                    download_script_code=self._safe_read_text(run_dir / "scripts" / "secure_download_reports.py"),
                    metadata={
                        key: value
                        for key, value in manifest.items()
                        if key
                        not in {
                            "run_id",
                            "created_at",
                            "seed_url",
                            "resolved_root_link",
                            "symbol",
                            "evaluation",
                            "reports",
                            "notes",
                            "trend_points",
                            "download_script_path",
                        }
                    },
                )
                return response
            except Exception:
                pass

        pdf_candidates = list((run_dir / "pdf").glob("*.pdf"))
        markdown_candidates = list((run_dir / "markdown").glob("*.md"))
        report_items = self._fallback_report_items(run_dir)
        notes = ["Reconstructed Harness 2 run from filesystem artifacts."]
        if not report_items and (pdf_candidates or markdown_candidates):
            notes.append("Run folder exists but report metadata was incomplete.")

        script_path = run_dir / "scripts" / "secure_download_reports.py"
        download_code = self._safe_read_text(script_path)
        if not download_code:
            script_path = run_dir / "secure_download_reports.py"
            download_code = self._safe_read_text(script_path)

        return Harness2BuildResponse(
            run_id=run_dir.name,
            created_at=self._coerce_datetime(None, run_dir),
            seed_url="",
            resolved_root_link="",
            symbol="",
            output_dir=str(run_dir),
            reports=report_items,
            trend_points=[],
            evaluation=Harness2Evaluation(
                root_link_ok=bool(report_items),
                pdf_download_rate=1.0 if pdf_candidates else 0.0,
                markdown_conversion_rate=1.0 if markdown_candidates else 0.0,
                internal_report_rate=1.0 if report_items else 0.0,
                trend_eval_coverage=0.0,
                trend_direction_accuracy=0.0,
                checklist={
                    "reconstructed_from_filesystem": True,
                    "manifest_missing_or_unreadable": True,
                },
            ),
            notes=notes,
            download_script_path=str(script_path),
            download_script_code=download_code,
            metadata={
                "reconstructed": True,
                "pdf_count": len(pdf_candidates),
                "markdown_count": len(markdown_candidates),
            },
        )

    def _matches_history_query(
        self,
        run: Harness2BuildResponse,
        q: Optional[str],
        symbol: Optional[str],
    ) -> bool:
        if symbol and symbol.strip():
            expected = symbol.strip().lower()
            if expected not in run.symbol.lower():
                return False

        if not q or not q.strip():
            return True

        needle = q.strip().lower()
        haystack = " ".join(
            [
                run.run_id,
                run.seed_url,
                run.resolved_root_link,
                run.symbol,
                run.output_dir,
                " ".join(run.notes),
                " ".join(report.title for report in run.reports),
                " ".join(report.source_url for report in run.reports),
                " ".join(report.summary for report in run.reports),
                " ".join(report.overview for report in run.reports),
                " ".join(report.further_direction for report in run.reports),
            ]
        ).lower()
        return needle in haystack

    def get_history(
        self,
        limit: int = 20,
        q: Optional[str] = None,
        symbol: Optional[str] = None,
        sort: str = "created_at",
        order: str = "desc",
    ) -> Harness2HistoryResponse:
        runs: List[Harness2BuildResponse] = []
        for run_dir in sorted(self._output_root().iterdir()):
            if not run_dir.is_dir():
                continue
            run = self._build_response_from_run_dir(run_dir)
            if run is None:
                continue
            if not self._matches_history_query(run, q=q, symbol=symbol):
                continue
            runs.append(run)

        sort_key_map = {
            "created_at": lambda item: item.created_at,
            "run_id": lambda item: item.run_id.lower(),
            "symbol": lambda item: item.symbol.lower(),
        }
        if sort not in sort_key_map:
            raise ValueError(f"Unsupported Harness 2 history sort: {sort}")
        reverse = order != "asc"
        runs.sort(key=sort_key_map[sort], reverse=reverse)

        safe_limit = max(1, min(limit, 100))
        return Harness2HistoryResponse(
            runs=runs[:safe_limit],
            total=len(runs),
            limit=safe_limit,
            q=q,
            symbol=symbol,
            sort=sort,  # type: ignore[arg-type]
            order=order,  # type: ignore[arg-type]
        )

    def _fetch_text(self, url: str) -> str:
        response = requests.get(url, timeout=self.timeout, headers=self.http_headers, allow_redirects=True)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text

    def _try_fetch_text_with_fallback(self, url: str) -> str:
        try:
            return self._fetch_text(url)
        except requests.HTTPError as exc:
            # Some investor pages block plain HTTP or non-browser clients.
            parsed = urlparse(url)
            if parsed.scheme == "http":
                https_url = parsed._replace(scheme="https").geturl()
                try:
                    return self._fetch_text(https_url)
                except Exception:
                    return self._fetch_text_via_mirror(https_url)
            try:
                return self._fetch_text_via_mirror(url)
            except Exception:
                raise exc
            raise exc

    def _extract_urls_from_text(self, text: str) -> List[str]:
        seen: set[str] = set()
        out: List[str] = []
        for m in _URL_RE.findall(text):
            candidate = m.strip().rstrip(".,;)")
            if candidate in seen:
                continue
            seen.add(candidate)
            out.append(candidate)
        return out

    def _is_safe_public_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").strip().lower()
        if not host:
            return False
        if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
            return False

        addrs: set[str] = set()
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                addrs.add(info[4][0])
        except Exception:
            return False

        for addr in addrs:
            try:
                ip = ipaddress.ip_address(addr)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
                    return False
            except ValueError:
                return False
        return True

    def _normalize_symbol(self, symbol: str) -> str:
        s = symbol.strip().lower()
        if not s:
            return s
        if "." in s:
            return s
        return f"{s}.us"

    def _extract_links(self, html: str, base_url: str) -> List[str]:
        links: List[str] = []
        seen: set[str] = set()
        for raw in _LINK_RE.findall(html):
            absolute = urljoin(base_url, raw.strip())
            parsed = urlparse(absolute)
            if parsed.scheme not in {"http", "https"}:
                continue
            if not self._is_safe_public_url(absolute):
                continue
            cleaned = absolute.split("#", 1)[0]
            if cleaned in seen:
                continue
            seen.add(cleaned)
            links.append(cleaned)
        return links

    def _llm_extract_root_link(self, markdown_text: str, model: str, temperature: float) -> str:
        excerpt = markdown_text[:12000]
        messages = [
            {
                "role": "system",
                "content": (
                    "You extract one best root URL for investor-report discovery. "
                    "Return only one absolute URL with http/https and no extra text."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Given this report text, find the most likely root page that links to historical financial PDFs "
                    "(investor relations, SEC filing index, annual/quarterly reports).\n\n"
                    f"REPORT_EXCERPT:\n{excerpt}"
                ),
            },
        ]
        raw = query_llm(messages=messages, model=model, temperature=temperature, max_tokens=256)
        candidates = self._extract_urls_from_text(raw)
        for candidate in candidates:
            if self._is_safe_public_url(candidate):
                return candidate
        raise ValueError("LLM could not return a safe root link")

    def _candidate_score(self, url: str) -> int:
        low = url.lower()
        score = 0
        if low.endswith(".pdf"):
            score += 30
        keywords = [
            "annual",
            "earnings",
            "quarter",
            "investor",
            "report",
            "results",
            "10-k",
            "10q",
            "financial",
        ]
        for kw in keywords:
            if kw in low:
                score += 5
        years = [int(y) for y in _YEAR_RE.findall(low)]
        if years:
            score += min(max(years) - 2015, 15)
        return score

    def _expand_pdf_candidates_from_html_pages(
        self,
        candidates: List[_Candidate],
        max_reports: int,
        notes: List[str],
    ) -> List[_Candidate]:
        if not candidates:
            return candidates

        expanded: List[_Candidate] = list(candidates)
        seen_urls: set[str] = {item.url.lower() for item in expanded}
        html_candidates = [item for item in candidates if not item.url.lower().endswith(".pdf")]

        # Crawl a few top HTML pages to discover nested PDF links.
        for item in html_candidates[: max(3, max_reports * 2)]:
            try:
                html = self._try_fetch_text_with_fallback(item.url)
            except Exception as exc:
                notes.append(f"Nested page fetch failed: {item.url} ({exc})")
                continue

            nested_links = self._extract_links(html, item.url)
            nested_links.extend(self._extract_urls_from_text(html))

            added_here = 0
            for link in nested_links:
                normalized = link.strip().split("#", 1)[0]
                if not normalized.lower().endswith(".pdf"):
                    continue
                if not self._is_safe_public_url(normalized):
                    continue
                key = normalized.lower()
                if key in seen_urls:
                    continue
                seen_urls.add(key)
                title = Path(urlparse(normalized).path).name or normalized
                score = self._candidate_score(normalized) + 10
                expanded.append(_Candidate(url=normalized, title=title, score=score))
                added_here += 1

            if added_here > 0:
                notes.append(f"Discovered {added_here} nested PDF link(s) from: {item.url}")

        return expanded

    def _discover_report_links(self, seed_url: str, max_reports: int) -> Tuple[str, List[_Candidate], List[str]]:
        notes: List[str] = []
        if not self._is_safe_public_url(seed_url):
            raise ValueError("Unsafe or non-public seed URL")

        html = ""
        links: List[str] = []
        try:
            html = self._try_fetch_text_with_fallback(seed_url)
            links = self._extract_links(html, seed_url)
        except Exception as exc:
            notes.append(f"Seed URL fetch blocked/unavailable: {seed_url} ({exc})")
            try:
                html = self._fetch_text_via_mirror(seed_url)
                links = self._extract_links(html, seed_url)
                notes.append("Seed URL recovered through public text mirror.")
            except Exception as mirror_exc:
                notes.append(f"Seed URL text mirror also failed: {seed_url} ({mirror_exc})")

        candidates: List[_Candidate] = []
        for link in links:
            score = self._candidate_score(link)
            if score <= 0:
                continue
            title = Path(urlparse(link).path).name or link
            candidates.append(_Candidate(url=link, title=title, score=score))

        if seed_url.lower().endswith(".pdf"):
            candidates.append(_Candidate(url=seed_url, title=Path(urlparse(seed_url).path).name or seed_url, score=100))

        if not candidates:
            notes.append("No direct report candidates found on seed page; trying root domain.")
            root_candidates: List[str] = []
            seed_parsed = urlparse(seed_url)
            if seed_parsed.scheme and seed_parsed.netloc:
                root_candidates.append(f"{seed_parsed.scheme}://{seed_parsed.netloc}")
                segments = [segment for segment in seed_parsed.path.split("/") if segment]
                for idx in range(len(segments), 0, -1):
                    root_candidates.append(
                        f"{seed_parsed.scheme}://{seed_parsed.netloc}/{'/'.join(segments[:idx])}"
                    )
            for root in dict.fromkeys(root_candidates):
                if not self._is_safe_public_url(root):
                    continue
                try:
                    html = self._try_fetch_text_with_fallback(root)
                    links = self._extract_links(html, root)
                    if links:
                        notes.append(f"Recovered links from root candidate: {root}")
                    for link in links:
                        score = self._candidate_score(link)
                        if score <= 0:
                            continue
                        title = Path(urlparse(link).path).name or link
                        candidates.append(_Candidate(url=link, title=title, score=score))
                    if candidates:
                        break
                except Exception as exc:
                    notes.append(f"Root-domain fetch blocked/unavailable: {root} ({exc})")
                    try:
                        html = self._fetch_text_via_mirror(root)
                        links = self._extract_links(html, root)
                        if links:
                            notes.append(f"Recovered links from mirror for root candidate: {root}")
                        for link in links:
                            score = self._candidate_score(link)
                            if score <= 0:
                                continue
                            title = Path(urlparse(link).path).name or link
                            candidates.append(_Candidate(url=link, title=title, score=score))
                        if candidates:
                            break
                    except Exception as mirror_exc:
                        notes.append(f"Root-domain text mirror also failed: {root} ({mirror_exc})")

        candidates = self._expand_pdf_candidates_from_html_pages(candidates, max_reports, notes)

        # Keep PDFs first; if URL is HTML filing page, still keep as fallback.
        candidates.sort(key=lambda c: (0 if c.url.lower().endswith(".pdf") else 1, -c.score, c.url))
        trimmed = candidates[: max_reports * 3]

        resolved_root = seed_url
        if trimmed:
            first = trimmed[0].url
            p = urlparse(first)
            directory = first.rsplit("/", 1)[0] if "/" in p.path else f"{p.scheme}://{p.netloc}"
            resolved_root = directory

        # Deduplicate by normalized path, then limit to max_reports.
        dedup: List[_Candidate] = []
        seen: set[str] = set()
        for c in trimmed:
            key = c.url.lower()
            if key in seen:
                continue
            seen.add(key)
            dedup.append(c)
            if len(dedup) >= max_reports:
                break

        if not dedup:
            notes.append("No downloadable report links discovered. Run will complete with empty report set.")

        return resolved_root, dedup, notes

    def _download_pdf(self, url: str, output_dir: Path, index: int) -> Optional[Path]:
        low = url.lower()
        if not low.endswith(".pdf"):
            return None
        if not self._is_safe_public_url(url):
            return None
        name = Path(urlparse(url).path).name or f"report_{index:02d}.pdf"
        path = output_dir / name
        response = requests.get(url, timeout=self.timeout, stream=True)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        if "pdf" not in content_type and not low.endswith(".pdf"):
            return None
        size = 0
        data = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            size += len(chunk)
            if size > self.max_download_bytes:
                return None
            data.extend(chunk)
        if len(data) < 1024:
            return None
        path.write_bytes(bytes(data))
        return path

    def _predict_trend_heuristic(self, markdown: str) -> str:
        low = markdown.lower()
        positive = ["increased", "growth", "record", "improved", "beat", "strong"]
        negative = ["decreased", "decline", "weakened", "loss", "miss", "downturn"]
        pos_score = sum(low.count(token) for token in positive)
        neg_score = sum(low.count(token) for token in negative)
        if pos_score > neg_score:
            return "up"
        if neg_score > pos_score:
            return "down"
        return "flat"

    def _render_download_script(self, pdf_urls: List[str], script_path: Path) -> str:
        allowed_hosts = sorted({urlparse(u).hostname for u in pdf_urls if urlparse(u).hostname})
        urls_literal = json.dumps(pdf_urls, indent=2)
        host_literal = json.dumps(allowed_hosts, indent=2)
        script = (
            "#!/usr/bin/env python3\n"
            "import ipaddress\n"
            "import socket\n"
            "from pathlib import Path\n"
            "from urllib.parse import urlparse\n"
            "import requests\n\n"
            f"PDF_URLS = {urls_literal}\n"
            f"ALLOWED_HOSTS = set({host_literal})\n"
            "MAX_BYTES = 50 * 1024 * 1024\n\n"
            "def safe_host(host: str) -> bool:\n"
            "    if not host or host not in ALLOWED_HOSTS:\n"
            "        return False\n"
            "    if host in {'localhost', '127.0.0.1', '0.0.0.0', '::1'} or host.endswith('.local'):\n"
            "        return False\n"
            "    try:\n"
            "        infos = socket.getaddrinfo(host, None)\n"
            "    except Exception:\n"
            "        return False\n"
            "    for info in infos:\n"
            "        ip = ipaddress.ip_address(info[4][0])\n"
            "        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:\n"
            "            return False\n"
            "    return True\n\n"
            "def main() -> None:\n"
            "    out = Path('downloads')\n"
            "    out.mkdir(parents=True, exist_ok=True)\n"
            "    for idx, url in enumerate(PDF_URLS, 1):\n"
            "        p = urlparse(url)\n"
            "        if p.scheme not in {'http', 'https'} or not safe_host((p.hostname or '').lower()):\n"
            "            print(f'[skip] unsafe URL: {url}')\n"
            "            continue\n"
            "        name = Path(p.path).name or f'report_{idx:02d}.pdf'\n"
            "        dst = out / name\n"
            "        with requests.get(url, timeout=20, stream=True) as resp:\n"
            "            resp.raise_for_status()\n"
            "            size = 0\n"
            "            with dst.open('wb') as f:\n"
            "                for chunk in resp.iter_content(chunk_size=65536):\n"
            "                    if not chunk:\n"
            "                        continue\n"
            "                    size += len(chunk)\n"
            "                    if size > MAX_BYTES:\n"
            "                        print(f'[skip] too large: {url}')\n"
            "                        f.close()\n"
            "                        dst.unlink(missing_ok=True)\n"
            "                        break\n"
            "                    f.write(chunk)\n"
            "            else:\n"
            "                print(f'[ok] {dst}')\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )
        script_path.write_text(script, encoding="utf-8")
        return script

    def _parse_json_object(self, text: str) -> Dict[str, object]:
        text = text.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            parsed = json.loads(m.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def _llm_analyze_report(
        self,
        markdown_text: str,
        title: str,
        source_url: str,
        analysis_profile: str,
        model: str,
        temperature: float,
    ) -> Dict[str, object]:
        question = "Company trend, key risks, and near-term direction"
        analysis_input = markdown_text
        if analysis_profile == "h1_all":
            _, analysis_input = build_retrieval_context(
                report_text=markdown_text,
                question=question,
                top_k=8,
                evidence_keywords=["revenue", "guidance", "margin", "cash flow", "risk"],
            )
        analysis_input = analysis_input[:18000]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a financial analyst. Respond in strict JSON only with keys: "
                    "summary, overview, further_direction, rating, predicted_trend. "
                    "rating must be 0..10; predicted_trend must be one of up/down/flat."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Title: {title}\n"
                    f"Source: {source_url}\n"
                    f"Profile: {analysis_profile}\n\n"
                    f"REPORT_CONTEXT:\n{analysis_input}"
                ),
            },
        ]
        raw = query_llm(messages=messages, model=model, temperature=temperature, max_tokens=900)
        parsed = self._parse_json_object(raw)
        if not parsed:
            return {
                "summary": raw[:500],
                "overview": "LLM returned non-JSON; fallback output used.",
                "further_direction": "Review source and rerun analysis.",
                "rating": 5.0,
                "predicted_trend": self._predict_trend_heuristic(markdown_text),
            }

        rating_value = parsed.get("rating", 5)
        try:
            rating = float(rating_value)
        except Exception:
            rating = 5.0
        rating = max(0.0, min(10.0, rating))
        trend = str(parsed.get("predicted_trend", "flat")).strip().lower()
        if trend not in {"up", "down", "flat"}:
            trend = self._predict_trend_heuristic(markdown_text)

        return {
            "summary": str(parsed.get("summary", "")).strip(),
            "overview": str(parsed.get("overview", "")).strip(),
            "further_direction": str(parsed.get("further_direction", "")).strip(),
            "rating": rating,
            "predicted_trend": trend,
        }

    def _extract_report_date(self, text: str, fallback_url: str) -> Optional[datetime]:
        match = _DATE_RE.search(text)
        if not match:
            match = _DATE_RE.search(fallback_url)
        if match:
            y, m, d = match.groups()
            try:
                return datetime(int(y), int(m), int(d), tzinfo=timezone.utc)
            except ValueError:
                return None

        # Fallback to year-only from URL/text.
        year_match = _YEAR_RE.search(fallback_url) or _YEAR_RE.search(text[:2000])
        if year_match:
            y = int(year_match.group(1))
            return datetime(y, 12, 31, tzinfo=timezone.utc)
        return None

    def _build_internal_report(
        self,
        markdown: str,
        title: str,
        source_url: str,
        summary: str,
        overview: str,
        further_direction: str,
        rating: float,
        predicted: str,
    ) -> str:
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        top = lines[:16]
        body = "\n".join(f"- {line[:180]}" for line in top)
        return (
            f"# Internal System Report\n\n"
            f"- Title: {title}\n"
            f"- Source: {source_url}\n"
            f"- Rating: {rating:.1f}/10\n"
            f"- Predicted trend: {predicted}\n\n"
            "## Summary\n"
            f"{summary}\n\n"
            "## Overview\n"
            f"{overview}\n\n"
            "## Further Direction\n"
            f"{further_direction}\n\n"
            "## Key extracted snippets\n"
            f"{body}\n"
        )

    def _fetch_price_series(self, symbol: str) -> Dict[datetime, float]:
        candidates: List[str] = []
        normalized = self._normalize_symbol(symbol)
        if normalized:
            candidates.append(normalized)
        plain = symbol.strip().lower()
        if plain and plain not in candidates:
            candidates.append(plain)
        upper = symbol.strip().upper()
        if upper and upper not in candidates:
            candidates.append(upper)
        # Stooq sometimes uses alternate tickers (for example, goog instead of googl).
        alias_map = {
            "googl": ["goog.us", "goog"],
            "goog": ["goog.us", "goog"],
            "brk.b": ["brk-b.us", "brk-b"],
        }
        aliases = alias_map.get(plain, [])
        for alias in aliases:
            if alias not in candidates:
                candidates.append(alias)
            alias_upper = alias.upper()
            if alias_upper not in candidates:
                candidates.append(alias_upper)

        for candidate in candidates:
            url = f"https://stooq.com/q/d/l/?s={candidate}&i=d"
            try:
                response = requests.get(url, timeout=self.timeout)
                response.raise_for_status()
                rows = [line.strip() for line in response.text.splitlines() if line.strip()]
                if not rows or not rows[0].lower().startswith("date,open,high,low,close"):
                    continue

                prices: Dict[datetime, float] = {}
                for row in rows[1:]:
                    parts = row.split(",")
                    if len(parts) < 5:
                        continue
                    try:
                        dt = datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                        close = float(parts[4])
                    except Exception:
                        continue
                    prices[dt] = close
                if prices:
                    return prices
            except Exception:
                continue

        return {}

    def _actual_trend(
        self,
        prices: Dict[datetime, float],
        report_date: Optional[datetime],
        horizon_days: int,
    ) -> Tuple[str, Optional[float], Optional[float], Optional[bool]]:
        if not report_date or not prices:
            return "unknown", None, None, None

        days = sorted(prices.keys())
        start_day = next((d for d in days if d >= report_date), None)
        if not start_day:
            return "unknown", None, None, None

        end_target = report_date + timedelta(days=horizon_days)
        end_day = next((d for d in days if d >= end_target), None)
        if not end_day:
            return "unknown", prices.get(start_day), None, None

        start_price = prices.get(start_day)
        end_price = prices.get(end_day)
        if start_price is None or end_price is None:
            return "unknown", start_price, end_price, None

        delta = end_price - start_price
        if abs(delta) < 1e-6:
            return "flat", start_price, end_price, None
        return ("up" if delta > 0 else "down"), start_price, end_price, None

    def _build_trend_points(self, prices: Dict[datetime, float], limit: int = 260) -> List[Harness2TrendPoint]:
        if not prices:
            return []
        days = sorted(prices.keys())[-limit:]
        return [Harness2TrendPoint(date=day.date().isoformat(), close=float(prices[day])) for day in days]

    def _run_pipeline(
        self,
        run_id: str,
        created_at: datetime,
        out_root: Path,
        seed_url: str,
        symbol: str,
        max_reports: int,
        horizon_days: int,
        analysis_profile: str,
        model: str,
        temperature: float,
        notes: List[str],
    ) -> Harness2BuildResponse:
        pdf_dir = out_root / "pdf"
        md_dir = out_root / "markdown"
        internal_dir = out_root / "internal_reports"
        scripts_dir = out_root / "scripts"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        md_dir.mkdir(parents=True, exist_ok=True)
        internal_dir.mkdir(parents=True, exist_ok=True)
        scripts_dir.mkdir(parents=True, exist_ok=True)

        resolved_root, candidates, discovery_notes = self._discover_report_links(seed_url, max_reports)
        notes.extend(discovery_notes)

        pdf_urls = [c.url for c in candidates if c.url.lower().endswith(".pdf")]
        script_path = scripts_dir / "secure_download_reports.py"
        script_code = self._render_download_script(pdf_urls, script_path)

        reports: List[Harness2ReportItem] = []
        downloaded = 0
        md_success = 0
        internal_success = 0

        prices: Dict[datetime, float] = {}
        try:
            prices = self._fetch_price_series(symbol)
        except Exception:
            prices = {}

        trend_compared = 0
        trend_correct = 0

        for idx, candidate in enumerate(candidates, 1):
            try:
                pdf_path = self._download_pdf(candidate.url, pdf_dir, idx)
                if pdf_path is None:
                    notes.append(f"Skipped non-PDF or invalid PDF candidate: {candidate.url}")
                    continue
                downloaded += 1

                md_result = convert_pdf_to_markdown(
                    str(pdf_path),
                    output_dir=str(md_dir),
                    output_name=f"{pdf_path.stem}.md",
                    overwrite=True,
                )
                md_success += 1

                md_text = Path(md_result.output_path).read_text(encoding="utf-8")
                analysis = self._llm_analyze_report(
                    markdown_text=md_text,
                    title=candidate.title,
                    source_url=candidate.url,
                    analysis_profile=analysis_profile,
                    model=model,
                    temperature=temperature,
                )

                predicted = str(analysis.get("predicted_trend", "flat"))
                summary = str(analysis.get("summary", ""))
                overview = str(analysis.get("overview", ""))
                further_direction = str(analysis.get("further_direction", ""))
                rating = float(analysis.get("rating", 5.0) or 5.0)
                report_date = self._extract_report_date(md_text, candidate.url)

                actual, p0, p1, _ = self._actual_trend(prices, report_date, horizon_days)
                correct: Optional[bool] = None
                if predicted in {"up", "down"} and actual in {"up", "down"}:
                    trend_compared += 1
                    correct = predicted == actual
                    if correct:
                        trend_correct += 1

                internal_text = self._build_internal_report(
                    markdown=md_text,
                    title=candidate.title,
                    source_url=candidate.url,
                    summary=summary,
                    overview=overview,
                    further_direction=further_direction,
                    rating=rating,
                    predicted=predicted,
                )
                internal_path = internal_dir / f"{pdf_path.stem}_internal.md"
                internal_path.write_text(internal_text, encoding="utf-8")
                internal_success += 1

                reports.append(
                    Harness2ReportItem(
                        title=candidate.title,
                        source_url=candidate.url,
                        pdf_path=str(pdf_path),
                        markdown_path=md_result.output_path,
                        internal_report_path=str(internal_path),
                        report_date=report_date.date().isoformat() if report_date else None,
                        predicted_trend=predicted,
                        actual_trend=actual,
                        trend_correct=correct,
                        price_start=p0,
                        price_end=p1,
                        summary=summary,
                        overview=overview,
                        further_direction=further_direction,
                        rating=rating,
                    )
                )
            except Exception as exc:
                notes.append(f"Failed candidate {candidate.url}: {exc}")

        total_targets = max(len(candidates), 1)
        evaluation = Harness2Evaluation(
            root_link_ok=bool(candidates),
            pdf_download_rate=round(downloaded / total_targets, 4),
            markdown_conversion_rate=round(md_success / max(downloaded, 1), 4),
            internal_report_rate=round(internal_success / max(md_success, 1), 4),
            trend_eval_coverage=round(trend_compared / max(internal_success, 1), 4),
            trend_direction_accuracy=round(trend_correct / max(trend_compared, 1), 4),
            checklist={
                "root_link_resolved": bool(candidates),
                "downloaded_pdf": downloaded > 0,
                "converted_pdf_to_md": md_success > 0,
                "built_internal_reports": internal_success > 0,
                "trend_validated_with_prices": trend_compared > 0,
            },
        )

        combined_ref_path = out_root / "system_reference.md"
        combined_content = "\n\n---\n\n".join(
            Path(item.internal_report_path).read_text(encoding="utf-8") for item in reports
        )
        combined_ref_path.write_text(combined_content, encoding="utf-8")

        trend_points = self._build_trend_points(prices)
        response = Harness2BuildResponse(
            run_id=run_id,
            created_at=created_at,
            seed_url=seed_url,
            resolved_root_link=resolved_root,
            symbol=symbol,
            output_dir=str(out_root),
            reports=reports,
            trend_points=trend_points,
            evaluation=evaluation,
            notes=notes,
            download_script_path=str(script_path),
            download_script_code=script_code,
            metadata={
                "system_reference_path": str(combined_ref_path),
                "candidate_count": len(candidates),
                "horizon_days": horizon_days,
                "analysis_profile": analysis_profile,
                "model": model,
                "temperature": temperature,
            },
        )

        manifest = {
            "run_id": run_id,
            "created_at": created_at.isoformat(),
            "seed_url": seed_url,
            "resolved_root_link": resolved_root,
            "symbol": symbol,
            "horizon_days": horizon_days,
            "analysis_profile": analysis_profile,
            "model": model,
            "temperature": temperature,
            "evaluation": evaluation.model_dump(),
            "reports": [r.model_dump() for r in reports],
            "notes": notes,
            "trend_points": [p.model_dump() for p in trend_points],
            "download_script_path": str(script_path),
        }
        (out_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return response

    def build_history_bundle(self, req: Harness2BuildRequest) -> Harness2BuildResponse:
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        out_root = self._output_root() / run_id
        out_root.mkdir(parents=True, exist_ok=True)
        return self._run_pipeline(
            run_id=run_id,
            created_at=created_at,
            out_root=out_root,
            seed_url=req.seed_url,
            symbol=req.symbol,
            max_reports=req.max_reports,
            horizon_days=req.horizon_days,
            analysis_profile=req.analysis_profile,
            model=req.model,
            temperature=req.temperature,
            notes=[],
        )

    def build_history_bundle_from_file(
        self,
        req: Harness2UploadBuildRequest,
        source_file_path: str,
        source_file_name: str,
    ) -> Harness2BuildResponse:
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc)
        out_root = self._output_root() / run_id
        out_root.mkdir(parents=True, exist_ok=True)
        input_dir = out_root / "input"
        input_dir.mkdir(parents=True, exist_ok=True)

        src = Path(source_file_path)
        file_name = source_file_name or src.name
        copied = input_dir / file_name
        shutil.copy2(src, copied)

        notes: List[str] = []
        if copied.suffix.lower() == ".pdf":
            md_result = convert_pdf_to_markdown(
                str(copied),
                output_dir=str(input_dir),
                output_name=f"{copied.stem}.md",
                overwrite=True,
            )
            source_md = Path(md_result.output_path)
            notes.append("Converted input PDF to markdown before root-link extraction.")
        elif copied.suffix.lower() == ".md":
            source_md = copied
        else:
            raise ValueError("Harness 2 upload supports only .md or .pdf")

        markdown_text = source_md.read_text(encoding="utf-8")
        extracted_root = ""
        try:
            extracted_root = self._llm_extract_root_link(markdown_text, req.model, req.temperature)
        except Exception as exc:
            notes.append(f"LLM root-link extraction failed: {exc}")

        if not extracted_root:
            for candidate in self._extract_urls_from_text(markdown_text):
                if self._is_safe_public_url(candidate):
                    extracted_root = candidate
                    notes.append("Fell back to first safe URL found in source markdown.")
                    break

        if not extracted_root:
            raise ValueError("Could not resolve a safe root link from the provided source file")

        return self._run_pipeline(
            run_id=run_id,
            created_at=created_at,
            out_root=out_root,
            seed_url=extracted_root,
            symbol=req.symbol,
            max_reports=req.max_reports,
            horizon_days=req.horizon_days,
            analysis_profile=req.analysis_profile,
            model=req.model,
            temperature=req.temperature,
            notes=notes,
        )


harness2_history_service = Harness2HistoryService()
