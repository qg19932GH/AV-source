import requests
from bs4 import BeautifulSoup
import re

class JavBusScraper:
    def __init__(self, base_url="https://www.javbus.com", proxy=None):
        self.base_url = base_url.rstrip('/')
        self.proxy = proxy
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8'
        }
        self.avatar_cache = {} # Cache to avoid duplicate requests for the same actress
        
    def get_proxies(self):
        if not self.proxy:
            return None
        proxy_url = self.proxy
        if not (proxy_url.startswith('http://') or proxy_url.startswith('https://') or proxy_url.startswith('socks5://')):
            proxy_url = f"http://{proxy_url}"
        return {
            'http': proxy_url,
            'https': proxy_url
        }

    def scrape_movie_details(self, code):
        code_upper = code.upper()
        # 1. Try direct page
        url = f"{self.base_url}/{code_upper}"
        proxies = self.get_proxies()
        
        try:
            response = requests.get(url, headers=self.headers, cookies={'age': 'verified'}, proxies=proxies, timeout=10)
            is_search = False
            
            if response.status_code == 404:
                # 2. Try search page
                search_url = f"{self.base_url}/search/{code_upper}"
                response = requests.get(search_url, headers=self.headers, cookies={'age': 'verified'}, proxies=proxies, timeout=10)
                is_search = True
                
            if response.status_code != 200:
                return None
                
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            
            if is_search:
                movie_box = soup.find('a', class_='movie-box')
                if movie_box:
                    detail_url = movie_box.get('href')
                    if detail_url and not detail_url.startswith('http'):
                        detail_url = self.base_url + detail_url
                    response = requests.get(detail_url, headers=self.headers, cookies={'age': 'verified'}, proxies=proxies, timeout=10)
                    if response.status_code != 200:
                        return None
                    response.encoding = 'utf-8'
                    soup = BeautifulSoup(response.text, 'html.parser')
                else:
                    return None # No match found
            
            # Now we are on the details page
            # Parse title
            title = ""
            title_h3 = soup.find('h3')
            if title_h3:
                title = title_h3.text.strip()
                
            # Parse cover image URL
            cover_url = ""
            big_image_a = soup.find('a', class_='bigImage')
            if big_image_a:
                cover_url = big_image_a.get('href')
                if cover_url and not cover_url.startswith('http'):
                    cover_url = self.base_url + cover_url
            
            # Parse actresses and their links
            actresses_info = []
            info_div = soup.find('div', class_='info')
            if info_div:
                for p in info_div.find_all('p'):
                    header_span = p.find('span', class_='header')
                    if header_span and ('演員' in header_span.text or '演员' in header_span.text or 'Cast' in header_span.text):
                        star_links = p.find_all('a')
                        for link in star_links:
                            name = link.text.strip()
                            star_href = link.get('href')
                            if name:
                                if star_href and not star_href.startswith('http'):
                                    star_href = self.base_url + star_href
                                actresses_info.append({'name': name, 'url': star_href})
            
            # Fallback to links matching /star/
            if not actresses_info:
                all_links = soup.find_all('a', href=re.compile(r'/star/'))
                for link in all_links:
                    name = link.text.strip()
                    star_href = link.get('href')
                    if name:
                        if star_href and not star_href.startswith('http'):
                            star_href = self.base_url + star_href
                        if not any(x['name'] == name for x in actresses_info):
                            actresses_info.append({'name': name, 'url': star_href})
                            
            return {
                'title': title,
                'cover_url': cover_url,
                'actresses': actresses_info
            }
        except Exception as e:
            print(f"Error scraping details for {code}: {e}")
            return None

    def get_avatar_url(self, star_url):
        if not star_url:
            return None
            
        if star_url in self.avatar_cache:
            return self.avatar_cache[star_url]
            
        proxies = self.get_proxies()
        try:
            response = requests.get(star_url, headers=self.headers, cookies={'age': 'verified'}, proxies=proxies, timeout=10)
            if response.status_code != 200:
                return None
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')
            avatar_box = soup.find('div', class_='avatar-box')
            if avatar_box:
                img = avatar_box.find('img')
                if img:
                    url = img.get('src')
                    if url and not url.startswith('http'):
                        url = self.base_url + url
                    self.avatar_cache[star_url] = url
                    return url
            # Fallback
            img = soup.find('img', src=lambda s: s and '/pics/actress/' in s)
            if img:
                url = img.get('src')
                if url and not url.startswith('http'):
                    url = self.base_url + url
                self.avatar_cache[star_url] = url
                return url
        except Exception as e:
            print(f"Error scraping star avatar at {star_url}: {e}")
        return None

    def download_image(self, url, save_path):
        if not url:
            return False
        proxies = self.get_proxies()
        headers = self.headers.copy()
        if 'dmm.co.jp' in url or 'dmm.com' in url:
            headers['Referer'] = 'https://www.dmm.co.jp/'
        elif 'javbus' in url:
            headers['Referer'] = self.base_url
            
        try:
            response = requests.get(url, headers=headers, proxies=proxies, timeout=15, stream=True)
            if response.status_code == 200:
                with open(save_path, 'wb') as f:
                    for chunk in response.iter_content(1024):
                        f.write(chunk)
                return True
        except Exception as e:
            print(f"Failed to download image from {url}: {e}")
        return False
