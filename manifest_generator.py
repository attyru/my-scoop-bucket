#!/usr/bin/env python3
import json
import hashlib
import requests
from pathlib import Path
from typing import Dict, Any, Optional
import sys

class ScoopManifestGenerator:
    def __init__(self, github_token: Optional[str] = None):
        self.session = requests.Session()
        self.session.timeout = 30  # [AI-FIX: Add default timeout for requests to prevent hanging on slow connections]
        if github_token:
            self.session.headers.update({
                'Authorization': f'token {github_token}',
                'Accept': 'application/vnd.github.v3+json'
            })
    
    def get_latest_release(self, repo: str) -> Dict[str, Any]:
        """Получает информацию о последнем релизе"""
        url = f"https://api.github.com/repos/{repo}/releases"
        # if not include_prerelease:
            # url += "/latest"
        # else:
        # Получаем все релизы, включая pre-release
        response = self.session.get(url)
        releases = response.json()
        return releases[0]  # первый = самый свежий
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
            
    def get_file_hash(self, url: str) -> str:
        """Скачивает файл и вычисляет SHA256"""
        print(f"Downloading and hashing: {url}")
        response = self.session.get(url, stream=True)
        response.raise_for_status()
        
        sha256_hash = hashlib.sha256()
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:  # [AI-FIX: Skip empty chunks to avoid updating hash with empty data]
                sha256_hash.update(chunk)
        
        return sha256_hash.hexdigest()
    
    def find_windows_assets(self, assets: list) -> Dict[str, str]:
        """Находит Windows бинарники в релизе"""
        windows_assets = {}
        
        for asset in assets:
            name = asset['name'].lower()
            if 'windows' in name or 'win' in name or name.endswith('.exe'):
                if 'x64' in name or 'amd64' in name or 'x86_64' in name:
                    # Используем #/rename для переименования файла при скачивании
                    url = asset['browser_download_url']
                    if asset['name'].endswith('.exe'):
                        # Переименовываем в простое имя
                        app_name = url.split('/')[-4]  # получаем имя репо
                        url += f"#/{app_name}.exe"
                    windows_assets['64bit'] = asset['browser_download_url']
                elif 'x86' in name or 'i686' in name or '32' in name:
                    windows_assets['32bit'] = asset['browser_download_url']
                else:
                    windows_assets['64bit'] = asset['browser_download_url']  # default
        
        return windows_assets
    
    def generate_manifest(self, repo: str, app_name: str = None, bin_name: str = None) -> Dict[str, Any]:
        """Генерирует манифест для Scoop"""
        release = self.get_latest_release(repo)
        
        if not app_name:
            app_name = repo.split('/')[-1]
        
        if not bin_name:
            bin_name = f"{app_name}.exe"
        
        version = release['tag_name'].lstrip('v')
        assets = self.find_windows_assets(release['assets'])
        
        if not assets:
            raise ValueError(f"No Windows assets found in {repo}")
        
        manifest = {
            "version": version,
            "description": release.get('body', f"{app_name} - {release['name']}").split('\n')[0],
            "homepage": f"https://github.com/{repo}",
            "license": "MIT",  # TODO: auto-detect from repo
            "architecture": {}
        }
        
        # Генерируем архитектуры с хешами
        for arch, url in assets.items():
            file_hash = self.get_file_hash(url)
            manifest["architecture"][arch] = {
                "url": url,
                "hash": file_hash,
                "bin": bin_name
            }
        
        # Автообновление
        if len(assets) == 1:
            # Один файл - простая схема
            arch = list(assets.keys())[0]
            url_template = assets[arch].replace(version, "$version")
            manifest["checkver"] = "github"
            manifest["autoupdate"] = {
                "architecture": {
                    arch: {"url": url_template}
                }
            }
        else:
            # Несколько архитектур
            manifest["checkver"] = "github"
            manifest["autoupdate"] = {"architecture": {}}
            for arch, url in assets.items():
                url_template = url.replace(version, "$version")
                manifest["autoupdate"]["architecture"][arch] = {"url": url_template}
        
        return manifest
    
    def save_manifest(self, manifest: Dict[str, Any], filename: str):
        """Сохраняет манифест в JSON файл"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=4, ensure_ascii=False)
        print(f"✓ Saved manifest: {filename}")

def main():
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
        
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()