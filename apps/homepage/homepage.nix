{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/homepage";
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/config 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.homepage = {
    image = "ghcr.io/gethomepage/homepage:latest";
    autoStart = true;
    ports = [ "3000:3000" ];
    volumes = [
      "${dataDir}/config:/app/config"
      "/var/run/docker.sock:/var/run/docker.sock:ro"
    ];
    environment = {
      TZ = config.steveos.timeZone or "Europe/Paris";
    };
  };

  networking.firewall.allowedTCPPorts = [ 3000 ];
}
