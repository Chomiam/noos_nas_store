{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/qbittorrent";
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/config 0775 ${user} users -"
    "d ${dataDir}/downloads 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.qbittorrent = {
    image = "lscr.io/linuxserver/qbittorrent:latest";
    autoStart = true;
    ports = [
      "8085:8085"
      "6881:6881"
      "6881:6881/udp"
    ];
    volumes = [
      "${dataDir}/config:/config"
      "${dataDir}/downloads:/downloads"
    ];
    environment = {
      PUID = "1000";
      PGID = "100";
      TZ = config.steveos.timeZone or "Europe/Paris";
      WEBUI_PORT = "8085";
    };
  };

  networking.firewall.allowedTCPPorts = [ 8085 6881 ];
  networking.firewall.allowedUDPPorts = [ 6881 ];
}
