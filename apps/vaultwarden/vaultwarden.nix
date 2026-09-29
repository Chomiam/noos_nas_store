{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/vaultwarden";
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/data 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.vaultwarden = {
    image = "vaultwarden/server:latest";
    autoStart = true;
    ports = [ "8222:80" ];
    volumes = [
      "${dataDir}/data:/data"
    ];
    environment = {
      ROCKET_PORT = "80";
      TZ = config.steveos.timeZone or "Europe/Paris";
    };
  };

  networking.firewall.allowedTCPPorts = [ 8222 ];
}
