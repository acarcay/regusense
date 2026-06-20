import requests
from bs4 import BeautifulSoup
url = "https://tr.wikipedia.org/wiki/TBMM_28._d%C3%B6nem_milletvekilleri_listesi"
headers = {"User-Agent": "Mozilla/5.0"}
res = requests.get(url, headers=headers)
soup = BeautifulSoup(res.text, "html.parser")
tables = soup.find_all("table", class_="wikitable")
for i, t in enumerate(tables):
    print(f"Tablo {i}: {len(t.find_all('tr'))} satır")
