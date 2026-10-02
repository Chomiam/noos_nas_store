#!/usr/bin/env python3
"""
Noos NAS Store — Portainer Templates Adapter & Ingestion Pipeline
Ce script télécharge les templates Portainer amont (ex: Lissy93/portainer-templates),
filtre les templates obsolètes ou défectueux, normalise les volumes et variables,
résout les Stacks Compose externes, et génère un catalogue Docker Compose 100% propre pour Noos.
"""

import os
import sys
import json
import re
import urllib.request
import urllib.error
import yaml
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SOURCE_URL = "https://raw.githubusercontent.com/Lissy93/portainer-templates/main/templates.json"
REPO_ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = REPO_ROOT / "apps"
STORE_JSON_PATH = REPO_ROOT / "store.json"

# Applications phares recommandées
RECOMMENDED_APPS = {
    "jellyfin", "plex", "nextcloud", "vaultwarden", "adguard", "adguardhome",
    "immich", "uptime-kuma", "qbittorrent", "transmission", "home-assistant",
    "homeassistant", "nginx-proxy-manager", "portainer", "paperless-ngx",
    "syncthing", "radarr", "sonarr", "lidarr", "bazarr", "prowlarr",
    "audiobookshelf", "photoprism", "mealie", "speedtest-tracker",
    "wireguard", "tailscale", "filebrowser", "duplicati", "flaresolverr",
    "overseerr", "jellyseerr", "calibre-web", "navidrome", "watchtower"
}

# Mapping des catégories anglaises vers les catégories harmonisées en français
CATEGORY_MAPPING = {
    "media": "Multimédia",
    "video": "Multimédia",
    "audio": "Multimédia",
    "music": "Multimédia",
    "photos": "Multimédia",
    "streaming": "Multimédia",
    "torrent": "Téléchargement",
    "torrents": "Téléchargement",
    "usenet": "Téléchargement",
    "download": "Téléchargement",
    "downloader": "Téléchargement",
    "security": "Sécurité & Réseau",
    "vpn": "Sécurité & Réseau",
    "network": "Sécurité & Réseau",
    "networking": "Sécurité & Réseau",
    "dns": "Sécurité & Réseau",
    "proxy": "Sécurité & Réseau",
    "privacy": "Sécurité & Réseau",
    "password": "Sécurité & Réseau",
    "administration": "Administration & Monitoring",
    "monitoring": "Administration & Monitoring",
    "dashboard": "Administration & Monitoring",
    "analytics": "Administration & Monitoring",
    "backup": "Administration & Monitoring",
    "docker": "Administration & Monitoring",
    "iot": "Domotique & IoT",
    "home": "Domotique & IoT",
    "automation": "Domotique & IoT",
    "smart": "Domotique & IoT",
    "utilities": "Outils & Utilitaires",
    "tools": "Outils & Utilitaires",
    "files": "Outils & Utilitaires",
    "sync": "Outils & Utilitaires",
    "dev": "Développement",
    "development": "Développement",
    "git": "Développement",
    "database": "Développement",
    "productivity": "Finance & Organisation",
    "finance": "Finance & Organisation",
    "notes": "Finance & Organisation",
    "wiki": "Finance & Organisation",
    "games": "Jeux & Divertissement",
    "gaming": "Jeux & Divertissement",
    "entertainment": "Jeux & Divertissement"
}

def clean_slug(name):
    """Génère un identifiant URL-friendly propre"""
    name = name.lower()
    name = re.sub(r'[^a-z0-9]+', '-', name)
    name = name.strip('-')
    return name

def harmonize_category(cats):
    """Détermine la meilleure catégorie française à partir d'une liste de catégories anglaises"""
    if not cats:
        return "Outils & Utilitaires"
    
    if isinstance(cats, str):
        cats = [cats]

    for cat in cats:
        cat_lower = cat.lower().strip()
        for key, val in CATEGORY_MAPPING.items():
            if key in cat_lower:
                return val

    return "Outils & Utilitaires"

def normalize_volume_path(host_path):
    """Assainit et transforme les chemins d'accès hôtes arbitraires en chemins relatifs ./data/..."""
    if not host_path:
        return "./data"
    
    # Nettoyer les chemins Portainer Files/AppData/...
    clean = re.sub(r'^/portainer/Files/AppData/[^/]+', './data', host_path, flags=re.IGNORECASE)
    clean = re.sub(r'^/srv/docker/[^/]+', './data', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^/docker/[^/]+', './data', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^/opt/[^/]+', './data', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^/var/lib/[^/]+', './data', clean, flags=re.IGNORECASE)
    
    # Ne pas toucher aux sockets et chemins système légitimes
    if host_path.startswith("/var/run/docker.sock") or host_path.startswith("/dev/"):
        return host_path

    # Si c'est un chemin absolu restant, le convertir sous ./data
    if clean.startswith("/"):
        parts = [p for p in clean.split("/") if p]
        suffix = parts[-1] if parts else "config"
        return f"./data/{suffix}"
    
    if not clean.startswith("./data"):
        clean = clean.lstrip("./")
        clean = f"./data/{clean}" if clean else "./data"

    return clean

def parse_ports(ports_list):
    """Extrait le port principal par défaut et les ports secondaires"""
    parsed = []
    for p in ports_list:
        if not p or not isinstance(p, str):
            continue
        # Format "8080:80/tcp" ou "8080:80" ou "8080"
        m = re.match(r'^(\d+)(?::(\d+))?(?:/(tcp|udp))?$', p.strip(), re.IGNORECASE)
        if m:
            host_port = int(m.group(1))
            proto = (m.group(3) or "tcp").upper()
            parsed.append((host_port, proto))
    
    if not parsed:
        return None, []
    
    default_p = parsed[0][0]
    extra_p = [p[0] for p in parsed[1:] if p[0] != default_p]
    return default_p, extra_p

def resolve_external_stackfile(repo_url, stackfile_path):
    """Télécharge et valide le fichier Docker Compose d'une Stack externe (type 3)"""
    if not repo_url or not stackfile_path:
        return None

    # Transformer https://github.com/owner/repo en raw.githubusercontent.com/owner/repo/main/...
    raw_base = repo_url.rstrip("/")
    if "github.com" in raw_base:
        raw_base = raw_base.replace("github.com", "raw.githubusercontent.com")
        raw_base = re.sub(r'\.git$', '', raw_base)

    clean_path = stackfile_path.lstrip("/")
    
    # Tester main puis master
    branches = ["main", "master"]
    for branch in branches:
        test_url = f"{raw_base}/{branch}/{clean_path}"
        try:
            req = urllib.request.Request(test_url, headers={"User-Agent": "Noos-Store-Importer/1.0"})
            with urllib.request.urlopen(req, timeout=8) as res:
                if res.status == 200:
                    content = res.read().decode('utf-8', errors='ignore')
                    # Valider qu'il s'agit bien de YAML valide
                    parsed_yaml = yaml.safe_load(content)
                    if isinstance(parsed_yaml, dict) and "services" in parsed_yaml and isinstance(parsed_yaml["services"], dict):
                        return content
        except Exception:
            continue

    return None

def normalize_compose_dict(compose_data, app_id):
    """Normalise un dictionnaire compose pour l'environnement Noos"""
    services = compose_data.get("services", {})
    if not services:
        return False

    for s_name, s_conf in services.items():
        if not isinstance(s_conf, dict):
            continue

        # Assurer restart policy saine
        if "restart" not in s_conf:
            s_conf["restart"] = "unless-stopped"

        # Normaliser les volumes
        vols = s_conf.get("volumes", [])
        if vols and isinstance(vols, list):
            new_vols = []
            for v in vols:
                if isinstance(v, str):
                    if ":" in v:
                        parts = v.split(":")
                        host = normalize_volume_path(parts[0])
                        cont = parts[1]
                        mode = f":{parts[2]}" if len(parts) > 2 else ""
                        new_vols.append(f"{host}:{cont}{mode}")
                    else:
                        new_vols.append(v)
                elif isinstance(v, dict):
                    src = v.get("source", "")
                    if src and not src.startswith("/") and not src.startswith("."):
                        v["source"] = f"./data/{src}"
                    elif src:
                        v["source"] = normalize_volume_path(src)
                    new_vols.append(v)
            s_conf["volumes"] = new_vols

    return True

def convert_type_1_to_compose(template):
    """Convertit un template de type 1 (conteneur simple) en fichier Compose v2 standard"""
    app_id = clean_slug(template.get("name") or template.get("title") or "app")
    image = template.get("image")
    if not image or not isinstance(image, str) or ":" not in image:
        image = f"{image}:latest" if image else None

    if not image:
        return None, None

    ports = template.get("ports", [])
    clean_ports = []
    for p in ports:
        if isinstance(p, str) and p.strip():
            clean_ports.append(p.strip())

    volumes = template.get("volumes", [])
    clean_volumes = []
    manifest_volumes = []

    for v in volumes:
        if isinstance(v, dict):
            cont = v.get("container")
            host = v.get("bind") or f"./data/{cont.strip('/').replace('/', '_')}"
            norm_host = normalize_volume_path(host)
            if cont:
                clean_volumes.append(f"{norm_host}:{cont}")
                manifest_volumes.append({
                    "host": norm_host,
                    "container": cont,
                    "description": f"Dossier {cont}"
                })

    # Si aucun volume n'est déclaré, assurer au moins un volume de configuration par défaut
    if not clean_volumes:
        clean_volumes.append("./data/config:/config")
        manifest_volumes.append({
            "host": "./data/config",
            "container": "/config",
            "description": "Données et configuration"
        })

    env_list = template.get("env", [])
    clean_env = {
        "PUID": "1000",
        "PGID": "100",
        "TZ": "Europe/Paris",
        "UMASK": "002"
    }
    manifest_envs = [
        {"name": "TZ", "label": "Fuseau horaire", "default": "Europe/Paris"},
        {"name": "PUID", "label": "User ID", "default": "1000"},
        {"name": "PGID", "label": "Group ID", "default": "100"}
    ]

    for e in env_list:
        if isinstance(e, dict):
            name = e.get("name")
            val = e.get("default", "")
            label = e.get("label", name)
            if name:
                clean_env[name] = str(val) if val is not None else ""
                if name not in ["PUID", "PGID", "TZ", "UMASK"]:
                    manifest_envs.append({
                        "name": name,
                        "label": label or name,
                        "default": str(val) if val is not None else ""
                    })

    service_def = {
        "container_name": app_id,
        "image": image,
        "restart": template.get("restart_policy") or "unless-stopped",
    }

    if clean_ports:
        service_def["ports"] = clean_ports
    if clean_volumes:
        service_def["volumes"] = clean_volumes
    if clean_env:
        service_def["environment"] = [f"{k}={v}" for k, v in clean_env.items()]

    compose_dict = {
        "services": {
            app_id: service_def
        }
    }

    compose_yaml = yaml.dump(compose_dict, default_flow_style=False, sort_keys=False)
    return compose_yaml, manifest_volumes, manifest_envs

def process_single_template(t):
    """Traite un template individuel et renvoie les données normalisées si valide"""
    try:
        t_type = t.get("type", 1)
        title = (t.get("title") or t.get("name") or "").strip()
        if not title:
            return None

        app_id = clean_slug(t.get("name") or title)
        if not app_id:
            return None

        # Exclure les templates Swarm et non-linux
        if t_type == 2 or t.get("platform") == "windows":
            return None

        description = (t.get("description") or t.get("note") or f"Application {title}").strip()
        categories = t.get("categories", ["Other"])
        main_cat = harmonize_category(categories)
        logo = t.get("logo") or f"https://cdn.jsdelivr.net/gh/selfhst/icons/png/{app_id}.png"
        website = t.get("website") or ""

        compose_content = None
        manifest_volumes = []
        manifest_envs = []
        default_port = None
        extra_ports = []

        if t_type == 1:
            res = convert_type_1_to_compose(t)
            if not res or not res[0]:
                return None
            compose_content, manifest_volumes, manifest_envs = res
            default_port, extra_ports = parse_ports(t.get("ports", []))

        elif t_type == 3:
            repo_info = t.get("repository", {})
            repo_url = repo_info.get("url")
            stackfile = repo_info.get("stackfile")
            if not repo_url or not stackfile:
                return None

            raw_yaml = resolve_external_stackfile(repo_url, stackfile)
            if not raw_yaml:
                return None

            try:
                parsed_compose = yaml.safe_load(raw_yaml)
                if not isinstance(parsed_compose, dict) or "services" not in parsed_compose:
                    return None
                
                if not normalize_compose_dict(parsed_compose, app_id):
                    return None

                # Extraire les ports du premier service
                for s_name, s_data in parsed_compose.get("services", {}).items():
                    if isinstance(s_data, dict) and "ports" in s_data:
                        default_port, extra_ports = parse_ports(s_data["ports"])
                        break

                compose_content = yaml.dump(parsed_compose, default_flow_style=False, sort_keys=False)
                manifest_volumes = [{"host": "./data", "container": "/data", "description": "Données de la stack"}]
                manifest_envs = [{"name": "TZ", "label": "Fuseau horaire", "default": "Europe/Paris"}]
            except Exception:
                return None

        if not compose_content:
            return None

        # Validation finale du compose.yaml généré
        test_parse = yaml.safe_load(compose_content)
        if not isinstance(test_parse, dict) or not test_parse.get("services"):
            return None

        is_rec = (app_id in RECOMMENDED_APPS) or any(r in app_id for r in RECOMMENDED_APPS)

        manifest = {
            "id": app_id,
            "name": title,
            "version": "latest",
            "category": main_cat,
            "tagline": description.split(".")[0][:120] if "." in description else description[:120],
            "description": description,
            "website": website,
            "icon": logo,
            "default_port": default_port or 8080,
            "extra_ports": extra_ports,
            "recommended": is_rec,
            "type": "compose",
            "compose_file": "compose.yaml",
            "volumes": manifest_volumes,
            "env": manifest_envs
        }

        return {
            "id": app_id,
            "manifest": manifest,
            "compose": compose_content
        }

    except Exception:
        return None

def main():
    print("=================================================================")
    print("🚀 Noos NAS Store — Démarrage du pipeline d'ingestion Portainer")
    print("=================================================================")

    print(f"📥 Téléchargement de la source amont : {SOURCE_URL}")
    try:
        req = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "Noos-Store-Importer/1.0"})
        with urllib.request.urlopen(req, timeout=15) as res:
            raw_data = json.loads(res.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ Erreur lors du téléchargement amont : {e}")
        sys.exit(1)

    templates = raw_data.get("templates", raw_data) if isinstance(raw_data, dict) else raw_data
    total_raw = len(templates)
    print(f"📦 {total_raw} templates détectés dans la collection amont.")

    APPS_DIR.mkdir(parents=True, exist_ok=True)

    valid_apps = []
    seen_ids = set()

    print("⚡ Traitement, assainissement et résolution des stacks Compose en parallèle...")
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(process_single_template, t): t for t in templates}
        for future in as_completed(futures):
            res = future.result()
            if res and res["id"] not in seen_ids:
                seen_ids.add(res["id"])
                valid_apps.append(res)

    # Trier les applications : Recommandées d'abord, puis par ordre alphabétique
    valid_apps.sort(key=lambda a: (not a["manifest"]["recommended"], a["manifest"]["name"].lower()))

    print(f"💾 Écriture des {len(valid_apps)} applications validées dans {APPS_DIR}...")
    final_store_apps = []

    for item in valid_apps:
        app_id = item["id"]
        manifest = item["manifest"]
        compose_yaml = item["compose"]

        app_dir = APPS_DIR / app_id
        app_dir.mkdir(parents=True, exist_ok=True)

        # 1. Écrire compose.yaml
        with open(app_dir / "compose.yaml", "w", encoding="utf-8") as f:
            f.write(compose_yaml)

        # 2. Écrire manifest.json
        with open(app_dir / "manifest.json", "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        final_store_apps.append(manifest)

    # Récupérer la liste des catégories uniques présentes
    categories = ["Tous"] + sorted(list(set(a["category"] for a in final_store_apps)))

    # Générer le store.json global consolidé
    store_catalog = {
        "version": "2.0.0",
        "updated_at": "2026-10-01T02:00:00Z",
        "repository": "https://github.com/Chomiam/noos_nas_store",
        "total_apps": len(final_store_apps),
        "categories": categories,
        "apps": final_store_apps
    }

    with open(STORE_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(store_catalog, f, indent=2, ensure_ascii=False)

    print("=================================================================")
    print(f"✨ Ingestion terminée avec succès !")
    print(f"📊 Applications traitées : {total_raw} amont ➔ {len(final_store_apps)} valides & sécurisées")
    print(f"📂 Fichier store.json généré : {STORE_JSON_PATH}")
    print(f"🏷️ Catégories disponibles : {', '.join(categories)}")
    print("=================================================================")

if __name__ == "__main__":
    main()
