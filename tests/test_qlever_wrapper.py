from SPARQLWrapper import SPARQLWrapper, JSON
sparql = SPARQLWrapper("https://qlever.cs.uni-freiburg.de/api/wikidata")
query = """
SELECT DISTINCT ?isim ?partiLabel ?unvanLabel WHERE {
  ?kisi wdt:P39 wd:Q486839 .
  ?kisi rdfs:label ?isim FILTER(LANG(?isim) = "tr")
} LIMIT 5
"""
sparql.setQuery(query)
sparql.setReturnFormat(JSON)
results = sparql.query().convert()
print(len(results["results"]["bindings"]))
