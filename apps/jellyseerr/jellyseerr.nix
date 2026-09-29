{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/jellyseerr";
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/config 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.jellyseerr = {
    image = "fallenbagel/jellyseerr:latest";
    autoStart = true;
    ports = [ "5055:5055" ];
    volumes = [
      "${dataDir}/config:/app/config"
    ];
    environment = {
      PORT = "5055";
      TZ = config.steveos.timeZone or "Europe/Paris";
    };
  };

  networking.firewall.allowedTCPPorts = [ 5055 ];
}
