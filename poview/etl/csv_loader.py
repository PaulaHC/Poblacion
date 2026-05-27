import requests

def descargar_csv(tabla):
    url = f"https://www.ine.es/jaxiT3/files/t/csv_bdsc/{tabla}.csv"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.content.decode("utf-8-sig")


def parse_csv(text):
    rows = [line.split(";") for line in text.splitlines() if line.strip()]
    return rows