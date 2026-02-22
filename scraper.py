import requests
import json
import os
import time
import string

PROGRESS_FILE = "progress/dubai_zones_progress.json"
RESULTS_FILE = "progress/dubai_zones_results.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "X-Airbnb-API-Key": "d306zoyjsyarp7ifhu67rjxn52tv0t20",
    "X-Csrf-Without-Token": "1",
    "referer": "https://www.airbnb.com/"
}

PARAMS_BASE = {
    "locale": "en-AE",
    "currency": "AED",
    "country": "AE",
    "language": "en",
    "key": "d306zoyjsyarp7ifhu67rjxn52tv0t20",
    "num_results": "10",
    "api_version": "1.2.0",
    "vertical_refinement": "homes",
    "region": "-1",
    "options": "should_filter_by_vertical_refinement|hide_nav_results|should_show_stays|simple_search",
    "satori_config_token": "EhIiQjIiMhISMhIiEhIiUkI1EBUIFXoKjgEFAA"
}

PROXY_USER = os.environ.get("PROXY_USER", "")
PROXY_PASS = os.environ.get("PROXY_PASS", "")
PROXY_HOST = os.environ.get("PROXY_HOST", "")
PROXY_PORT = os.environ.get("PROXY_PORT", "")


def get_proxies():
    if PROXY_HOST and PROXY_USER:
        proxy_url = f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}:{PROXY_PORT}"
        return {"http": proxy_url, "https": proxy_url}
    return None


def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {
        "completed": [],
        "pending_n2": [],
        "pending_n3": [],
        "zones": {}
    }


def save_progress(progress):
    os.makedirs("progress", exist_ok=True)
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def save_results(zones):
    order = {"city": 0, "district": 1, "neighborhood": 2, "area": 3}
    result = []
    for z in zones.values():
        types = z.get("types", "")
        if "locality" in types:
            zone_type = "city"
        elif "sublocality" in types:
            zone_type = "district"
        elif "neighborhood" in types:
            zone_type = "neighborhood"
        else:
            zone_type = "area"
        result.append({**z, "zone_type": zone_type})
    result.sort(key=lambda x: (order.get(x["zone_type"], 3), x["name"]))
    os.makedirs("progress", exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"✅ {len(result)} zones sauvegardées dans {RESULTS_FILE}")


def query_airbnb(user_input, retries=3):
    params = {**PARAMS_BASE, "user_input": user_input}
    proxies = get_proxies()
    for attempt in range(retries):
        try:
            r = requests.get(
                "https://www.airbnb.com/api/v2/autocompletes-personalized",
                params=params,
                headers=HEADERS,
                proxies=proxies,
                timeout=15
            )
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"⚠️ 429 sur '{user_input}' - attente {wait}s")
                time.sleep(wait)
                continue
            if r.status_code == 200:
                data = r.json()
                # L'API retourne une liste, on prend le premier élément
                if isinstance(data, list) and len(data) > 0:
                    return data[0] if isinstance(data[0], dict) else None
                elif isinstance(data, dict):
                    return data
                else:
                    return None
        except Exception as e:
            print(f"❌ Erreur sur '{user_input}': {e}")
            time.sleep(10)
    return None


def extract_ae_zones(data, progress, prefix, next_level_pending_key):
    if not data:
        return 0
    terms = data.get("autocomplete_terms", [])
    ae_terms = [
        t for t in terms
        if t.get("location", {}).get("country_code") == "AE"
        and t.get("suggestion_type") == "LOCATION"
    ]
    for term in ae_terms:
        place_id = term.get("explore_search_params", {}).get("place_id", "")
        if place_id and place_id not in progress["zones"]:
            progress["zones"][place_id] = {
                "name": term.get("display_name", ""),
                "place_id": place_id,
                "types": ", ".join(term.get("location", {}).get("types", []))
            }
    # Si 10 résultats AE → approfondir cette branche (sauf si on est au dernier niveau)
    if len(ae_terms) >= 10 and next_level_pending_key in progress:
        for l in string.ascii_uppercase:
            new_query = f"Dubai {prefix}{l}"
            new_prefix = f"{prefix}{l}"
            if new_query not in progress["completed"] and \
               not any(q["query"] == new_query for q in progress[next_level_pending_key]):
                progress[next_level_pending_key].append({
                    "query": new_query,
                    "prefix": new_prefix
                })
    return len(ae_terms)


def process_queries(queries, progress, next_level_key, level_name, batch_size=50, delay=3):
    total = len(queries)
    print(f"\n🔄 {level_name}: {total} requêtes à traiter")
    processed = 0
    for i, q in enumerate(queries):
        query = q["query"]
        prefix = q["prefix"]
        if query in progress["completed"]:
            continue
        data = query_airbnb(query)
        count = extract_ae_zones(data, progress, prefix, next_level_key)
        progress["completed"].append(query)
        processed += 1
        print(f"  [{i+1}/{total}] '{query}' → {count} zones AE | Total: {len(progress['zones'])}")
        # Sauvegarder tous les 50
        if processed % batch_size == 0:
            save_progress(progress)
            save_results(progress["zones"])
            print(f"💾 Sauvegarde intermédiaire après {processed} requêtes")
        time.sleep(delay)
    # Sauvegarde finale du niveau
    save_progress(progress)
    save_results(progress["zones"])


def main():
    progress = load_progress()
    print(f"📂 Reprise: {len(progress['zones'])} zones, {len(progress['completed'])} requêtes complétées")

    # NIVEAU 1 : Dubai A → Dubai Z
    n1_queries = [
        {"query": f"Dubai {l}", "prefix": l}
        for l in string.ascii_uppercase
        if f"Dubai {l}" not in progress["completed"]
    ]
    if n1_queries:
        process_queries(n1_queries, progress, "pending_n2", "N1")
    else:
        print("✅ N1 déjà complété")

    # NIVEAU 2 : Dubai AA → Dubai ZZ (seulement branches saturées)
    n2_queries = [q for q in progress["pending_n2"] if q["query"] not in progress["completed"]]
    if n2_queries:
        process_queries(n2_queries, progress, "pending_n3", "N2")
    else:
        print("✅ N2 déjà complété ou pas nécessaire")

    # NIVEAU 3 : Dubai AAA → Dubai ZZZ (seulement branches saturées)
    n3_queries = [q for q in progress["pending_n3"] if q["query"] not in progress["completed"]]
    if n3_queries:
        process_queries(n3_queries, progress, "_none", "N3")
    else:
        print("✅ N3 déjà complété ou pas nécessaire")

    print(f"\n🏁 TERMINÉ: {len(progress['zones'])} zones Dubai trouvées")


if __name__ == "__main__":
    main()
