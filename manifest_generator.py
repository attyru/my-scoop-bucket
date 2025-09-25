#!/usr/bin/env python3
import json
import hashlib
import requests
from pathlib import Path
from typing import Dict, Any, Optional
import sys
import logging
import re

class ScoopManifestGenerator:
    def __init__(self, github_token: Optional[str] = None):
        self.session = requests.Session()
        self.session.timeout = 30
        if github_token:
            self.session.headers.update({
                'Authorization': f'token {github_token}',
                'Accept': 'application/vnd.github.v3+json'
            })
    
    def get_latest_release(self, repo: str) -> Dict[str, Any]:
        """Получает информацию о последнем релизе"""
        url = f"https://api.github.com/repos/{repo}/releases"
        response = self.session.get(url)
        response.raise_for_status()
        releases = response.json()
        if not releases:
            raise ValueError("No releases found for the repository")
        return releases[0]  # первый = самый свежий
            
    def get_file_hash(self, url: str) -> str:
        """Скачивает файл и вычисляет SHA256"""
        logging.info(f"Downloading and hashing: {url}")
        response = self.session.get(url, stream=True)
        response.raise_for_status()
        
        content_length = response.headers.get('Content-Length')
        if content_length and int(content_length) > 100 * 1024 * 1024:  # 100MB limit
            raise ValueError(f"File too large: {content_length} bytes")
        
        sha256_hash = hashlib.sha256()
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    
    def find_windows_assets(self, assets: list) -> Dict[str, str]:
        """Находит Windows бинарники в релизе"""
        
        win_assets = {}
        
        for asset in assets:
            name = asset['name'].lower()
            
            # Только windows файлы
            is_windows = name.endswith('.exe') or name.endswith('.zip')
            
            if not is_windows:
                continue
                
            url = asset['browser_download_url']
            
            # # Определяем архитектуру регексами
            if re.search(r'amd64-v3|x86_64-v3', name):
                win_assets['64bit-v3'] = url
            elif re.search(r'amd64|x86_64', name):
                win_assets['64bit'] = url
            elif re.search(r'x86', name):
                win_assets['32bit'] = url
            elif re.search(r'arm64|arm32|armv7|386|686|linux|darwin|freebsd|macos', name):
                continue
            else:
                win_assets['unknown'] = url
        
        return win_assets
    
    def generate_manifest(self, repo: str, app_name: Optional[str] = None, bin_name: Optional[str] = None) -> Dict[str, Any]:
        """Генерирует манифест для Scoop"""
        release = self.get_latest_release(repo)
        
        # Определяем имена
        if not app_name:
            app_name = repo.split('/')[-1]
        if not bin_name:
            bin_name = f"{app_name.lower()}.exe"
        
        # Находим Windows ассеты
        windows_assets = self.find_windows_assets(release['assets'])
        
        if not windows_assets:
            raise ValueError("No Windows assets found in the release")
        
        license_info = release.get('license', {}).get('spdx_id', 'Unknown') if release.get('license') else 'Unknown'
        
        # Базовая структура манифеста
        manifest = {
            "version": release['tag_name'].lstrip('v'),
            "description": release.get('body', '').split('\n')[0][:100] if release.get('body') else f"{app_name} - GitHub release",
            "homepage": f"https://github.com/{repo}",
            "license": license_info,
            "notes": release.get('body', ''),
        }
        
        # Добавляем архитектуры и хеши
        if len(windows_assets) == 1:
            # Только одна архитектура
            arch, url = next(iter(windows_assets.items()))
            manifest.update({
                "url": url,
                "hash": self.get_file_hash(url),
                "bin": bin_name
            })
        else:
            # Несколько архитектур
            manifest["architecture"] = {}
            for arch, url in windows_assets.items():
                manifest["architecture"][arch] = {
                    "url": url,
                    "hash": self.get_file_hash(url),
                    "bin": bin_name
                }
        
        return manifest
    
    def save_manifest(self, manifest: Dict[str, Any], filename: str) -> None:
        """Сохраняет манифест в файл"""
        safe_filename = Path(filename).name  # Only take the basename
        with open(safe_filename, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        logging.info(f"✓ Saved manifest: {safe_filename}")

def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    if len(sys.argv) < 2:
        print("Usage: python manifest_generator.py <github_repo> [app_name] [bin_name]")
        print("Example: python manifest_generator.py ikatson/rqbit rqbit rqbit.exe")
        sys.exit(1)
    
    repo = sys.argv[1]
    app_name = sys.argv[2] if len(sys.argv) > 2 else None
    bin_name = sys.argv[3] if len(sys.argv) > 3 else None
    
    generator = ScoopManifestGenerator()
    
    try:
        manifest = generator.generate_manifest(repo, app_name, bin_name)
        filename = f"{app_name or repo.split('/')[-1]}.json"
        generator.save_manifest(manifest, filename)
        
        print(f"\n🎉 Generated manifest for {repo}")
        print(f"Now run: git add {filename} && git commit -m 'Add {app_name}' && git push")
        
    except requests.RequestException as e:
        logging.error(f"Network error: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"Validation error: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()