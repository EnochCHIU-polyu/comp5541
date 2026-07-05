#!/usr/bin/env python3
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse
import requests

PDF_URLS = [
  "https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/2026q1-alphabet-earnings-release.pdf",
  "https://s206.q4cdn.com/479360582/files/doc_financials/2026/q1/Alphabet-Q1-2026-Earnings-Slides.pdf",
  "https://s206.q4cdn.com/479360582/files/doc_financials/2025/q1/2025q1-alphabet-earnings-release.pdf",
  "https://s206.q4cdn.com/479360582/files/doc_financials/2025/q1/2025q1-alphabet-earnings-slides.pdf",
  "https://s206.q4cdn.com/479360582/files/doc_financials/2025/q2/2025q2-alphabet-earnings-release.pdf"
]
ALLOWED_HOSTS = set([
  "s206.q4cdn.com"
])
MAX_BYTES = 50 * 1024 * 1024

def safe_host(host: str) -> bool:
    if not host or host not in ALLOWED_HOSTS:
        return False
    if host in {'localhost', '127.0.0.1', '0.0.0.0', '::1'} or host.endswith('.local'):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast:
            return False
    return True

def main() -> None:
    out = Path('downloads')
    out.mkdir(parents=True, exist_ok=True)
    for idx, url in enumerate(PDF_URLS, 1):
        p = urlparse(url)
        if p.scheme not in {'http', 'https'} or not safe_host((p.hostname or '').lower()):
            print(f'[skip] unsafe URL: {url}')
            continue
        name = Path(p.path).name or f'report_{idx:02d}.pdf'
        dst = out / name
        with requests.get(url, timeout=20, stream=True) as resp:
            resp.raise_for_status()
            size = 0
            with dst.open('wb') as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > MAX_BYTES:
                        print(f'[skip] too large: {url}')
                        f.close()
                        dst.unlink(missing_ok=True)
                        break
                    f.write(chunk)
            else:
                print(f'[ok] {dst}')

if __name__ == '__main__':
    main()
