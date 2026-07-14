import httpx
import json

query = """
SELECT DISTINCT ?isim ?partiLabel ?unvanLabel WHERE {
  ?kisi wdt:P39 wd:Q486839 .
  ?kisi rdfs:label ?isim FILTER(LANG(?isim) = "tr")
} LIMIT 10
"""
url = "https://qlever.cs.uni-freiburg.de/api/wikidata"
with httpx.Client(follow_redirects=True) as client:
    response = client.post(url, data={"query": query}, headers={"Accept": "application/json"})
    print(response.status_code)
    try:
        print(list(response.json().keys()))
    except:
        print(response.text[:200])
