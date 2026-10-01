#!/usr/bin/env python3
"""
STEvE_OS NAS Store — Filtre et Validateur de Qualité Avancé
Ce script audite rigoureusement toutes les applications du catalogue :
1. Test de conformité Docker Compose specification via `docker compose config`.
2. Détection et exclusion des applications dépréciées (keywords: deprecated, eol, etc.).
3. Vérification de la vivacité et de la maintenance des images sur Docker Hub (exclusion des dépôts 404 et des images abandonnées depuis des années).
4. Épuration physique des dossiers `apps/<id>` rejetés et régénération propre de `store.json`.
"""

import os
import sys
import json
import shutil
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = REPO_ROOT / "apps"
STORE_JSON_PATH = REPO_ROOT / "store.json"

# Seuil de péremption : toute image non mise à jour depuis le 1er janvier 2023 (plus de 3 ans) est considérée comme abandonnée
CUTOFF_YEAR = 2023

# Mots-clés indiquant l'abandon ou la dépréciation
DEPRECATED_KEYWORDS = [
    "deprecated", "unmaintained", "no longer maintained",
    "discontinued", "archived", "outdated", "end of life",
    "eol", "abandoned", "not maintained", "legacy only"
]

# Applications système ou utilitaires historiques tolérés même sans mise à jour récente
IMAGE_WHITELIST = {
    "hello-world", "traefik/whoami", "containrrr/watchtower"
}

dockerhub_cache = {}

def get_dockerhub_info(repo):
    """Interroge Docker Hub pour connaître l'état du dépôt et sa date de dernière mise à jour"""
    if repo in dockerhub_cache:
        return dockerhub_cache[repo]

    clean_repo = repo.split(":")[0]
    if "/" not in clean_repo:
        clean_repo = f"library/{clean_repo}"

    url = f"https://hub.docker.com/v2/repositories/{clean_repo}/"
    req = urllib.request.Request(url, headers={"User-Agent": "STEvE_OS-Store-Auditor/1.0"})

    try:
        with urllib.request.urlopen(req, timeout=6) as res:
            data = json.loads(res.read().decode('utf-8'))
            last_updated = data.get("last_updated") or ""
            info = {
                "status": "ok",
                "last_updated": last_updated,
                "year": int(last_updated[:4]) if len(last_updated) >= 4 and last_updated[:4].isdigit() else 2025
            }
            dockerhub_cache[repo] = info
            return info
    except urllib.error.HTTPError as e:
        if e.code == 404:
            info = {"status": "404", "error": "Repository not found (404)"}
        elif e.code == 429:
            info = {"status": "rate_limited", "error": "Rate limit reached (429)"}
        else:
            info = {"status": "http_error", "code": e.code}
        dockerhub_cache[repo] = info
        return info
    except Exception as e:
        info = {"status": "error", "error": str(e)}
        dockerhub_cache[repo] = info
        return info

def audit_app(app_dir):
    """Audite une application individuelle et retourne (app_id, isValid, reason, manifest)"""
    app_id = app_dir.name
    compose_file = app_dir / "compose.yaml"
    manifest_file = app_dir / "manifest.json"

    if not compose_file.exists() or not manifest_file.exists():
        return app_id, False, "Fichiers compose.yaml ou manifest.json manquants", None

    try:
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return app_id, False, f"manifest.json corrompu: {e}", None

    try:
        with open(compose_file, "r", encoding="utf-8") as f:
            compose_data = yaml.safe_load(f)
    except Exception as e:
        return app_id, False, f"compose.yaml YAML invalide: {e}", None

    if not isinstance(compose_data, dict) or "services" not in compose_data or not compose_data["services"]:
        return app_id, False, "compose.yaml ne contient aucune section 'services' valide", manifest

    # 1. Vérification des mots-clés de dépréciation dans la description / nom
    full_text = f"{manifest.get('name', '')} {manifest.get('tagline', '')} {manifest.get('description', '')}".lower()
    for kw in DEPRECATED_KEYWORDS:
        if re_word_match(kw, full_text):
            return app_id, False, f"Projet déprécié ou abandonné (mot-clé détecté: '{kw}')", manifest

    # 2. Validation de la syntaxe Docker Compose via le CLI
    compose_cmd = ["docker", "compose", "-f", str(compose_file), "config", "-q"]
    try:
        proc = subprocess.run(compose_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
        if proc.returncode != 0:
            err_msg = proc.stderr.strip().split("\n")[0] if proc.stderr else "Erreur de syntaxe compose"
            return app_id, False, f"Échec validation Docker Compose Spec: {err_msg}", manifest
    except FileNotFoundError:
        # Si docker compose n'est pas dispo en local, essayer podman-compose
        try:
            proc = subprocess.run(["podman-compose", "-f", str(compose_file), "config"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=8)
            if proc.returncode != 0:
                return app_id, False, f"Échec validation Podman Compose: {proc.stderr[:120]}", manifest
        except Exception:
            pass
    except Exception as e:
        return app_id, False, f"Erreur exécution validation compose: {e}", manifest

    # 3. Extraction et contrôle de fraîcheur des images
    services = compose_data.get("services", {})
    images_to_check = []
    for s_name, s_data in services.items():
        if not isinstance(s_data, dict):
            continue
        img = s_data.get("image")
        if not img or not isinstance(img, str):
            return app_id, False, f"Service '{s_name}' sans image Docker définie", manifest
        images_to_check.append(img)

    for img in images_to_check:
        clean_img = img.split(":")[0]
        if clean_img in IMAGE_WHITELIST:
            continue

        # Vérifier si l'image est sur Docker Hub (pas de domaine personnalisé comme ghcr.io, quay.io, lscr.io)
        if not clean_img.startswith("ghcr.io/") and not clean_img.startswith("quay.io/") and not clean_img.startswith("lscr.io/") and not clean_img.startswith("gcr.io/"):
            info = get_dockerhub_info(clean_img)
            if info["status"] == "404":
                return app_id, False, f"Image introuvable sur Docker Hub (404 Not Found): {img}", manifest
            elif info["status"] == "ok":
                year = info.get("year", 2025)
                if year < CUTOFF_YEAR and not manifest.get("recommended", False):
                    last_up = info.get("last_updated", "")[:10]
                    return app_id, False, f"Image Docker Hub abandonnée (dernière mise à jour: {last_up}, seuil minimum: {CUTOFF_YEAR}): {img}", manifest

    return app_id, True, "OK", manifest

def re_word_match(keyword, text):
    """Recherche d'un mot ou d'une expression entouré de frontières"""
    import re
    pattern = r'\b' + re.escape(keyword) + r'\b'
    return bool(re.search(pattern, text))

def main():
    print("=================================================================")
    print("🛡️ STEvE_OS NAS Store — Audit & Filtrage Qualité Automatique")
    print("=================================================================")

    if not APPS_DIR.exists():
        print(f"❌ Dossier apps/ introuvable à {APPS_DIR}")
        sys.exit(1)

    app_folders = [d for d in APPS_DIR.iterdir() if d.is_dir()]
    total_found = len(app_folders)
    print(f"🔍 {total_found} applications détectées à auditer dans {APPS_DIR}...")

    valid_manifests = []
    rejected = []

    # Utiliser un pool de threads pour auditer rapidement avec vérification Docker Hub
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(audit_app, d): d for d in app_folders}
        for future in as_completed(futures):
            app_id, is_valid, reason, manifest = future.result()
            if is_valid and manifest:
                valid_manifests.append(manifest)
            else:
                rejected.append((app_id, reason))

    print(f"\n📊 Résultats de l'audit :")
    print(f"  ✅ Valides et maintenues : {len(valid_manifests)}")
    print(f"  ❌ Rejetées / Écartées   : {len(rejected)}")

    if rejected:
        print("\n🗑️ Exemples d'applications rejetées et raisons :")
        for r_id, r_reason in sorted(rejected, key=lambda x: x[0])[:25]:
            print(f"  - [{r_id}]: {r_reason}")

        # Purge physique des dossiers rejetés
        print("\n🧹 Suppression physique des dossiers d'applications non conformes...")
        for r_id, _ in rejected:
            r_dir = APPS_DIR / r_id
            if r_dir.exists():
                shutil.rmtree(r_dir, ignore_errors=True)

    # Réorganiser et trier les applications saines
    valid_manifests.sort(key=lambda a: (not a.get("recommended", False), a.get("name", "").lower()))

    # Calculer les catégories
    categories = ["Tous"] + sorted(list(set(a["category"] for a in valid_manifests if a.get("category"))))

    # Régénérer store.json
    store_catalog = {
        "version": "2.0.0",
        "updated_at": "2026-10-01T02:00:00Z",
        "repository": "https://github.com/Chomiam/steveos_nas_store",
        "total_apps": len(valid_manifests),
        "categories": categories,
        "apps": valid_manifests
    }

    with open(STORE_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(store_catalog, f, indent=2, ensure_ascii=False)

    print(f"\n✨ store.json régénéré avec succès : {len(valid_manifests)} applications certifiées.")
    print("=================================================================")

if __name__ == "__main__":
    main()
