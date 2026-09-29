{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/uptime-kuma";
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/data 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.uptime-kuma = {
    image = "louislam/uptime-kuma:latest";
    autoStart = true;
    ports = [ "3001:3001" ];
    volumes = [
      "${dataDir}/data:/app/data"
    ];
    environment = {
      TZ = config.steveos.timeZone or "Europe/Paris";
    };
  };

  networking.firewall.allowedTCPPorts = [ 3001 ];
}
