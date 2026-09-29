# 🛍️ STEvE_OS NAS Store

Boutique officielle et catalogue déclaratif d'applications Docker pour **STEvE_OS NAS Edition**.

## 📖 Fonctionnement

Chaque application disponible dans ce catalogue est préconfigurée pour l'environnement NixOS :
- Les données persistantes sont stockées de façon uniforme dans `/home/<user>/docker/<app_id>/`.
- Les permissions utilisateur sont créées déclarativement (`0775 <user>:users`).
- Le conteneur est géré sous forme de service systemd via `virtualisation.oci-containers`.
- Les ports requis sont déclarés et ouverts dans le pare-feu NixOS.

## 📦 Applications disponibles

| Application | Catégorie | Port | Description |
| :--- | :--- | :--- | :--- |
| **Arcane** | Administration | 3552 | Gestionnaire moderne et léger de conteneurs Docker |
| **Immich** | Multimédia | 2283 | Hébergement de photos et vidéos type Google Photos |
| **Jellyseerr** | Multimédia | 5055 | Gestionnaire de requêtes de médias pour Jellyfin |
| **qBittorrent** | Téléchargement | 8085 | Client BitTorrent rapide avec interface web |
| **Vaultwarden** | Sécurité | 8222 | Coffre-fort de mots de passe compatible Bitwarden |
| **Uptime Kuma** | Monitoring | 3001 | Surveillance de disponibilité de services et sites |
| **Homepage** | Administration | 3000 | Tableau de bord moderne pour homelab |
| **FileBrowser** | Outils | 8082 | Explorateur de fichiers Web réactif |

