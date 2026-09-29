{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/immich";
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/upload 0775 ${user} users -"
    "d ${dataDir}/profile 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.immich = {
    image = "ghcr.io/immich-app/immich-server:release";
    autoStart = true;
    ports = [ "2283:2283" ];
    volumes = [
      "${dataDir}/upload:/usr/src/app/upload"
      "${dataDir}/profile:/usr/src/app/profile"
    ];
    environment = {
      IMMICH_ENV = "production";
      TZ = config.steveos.timeZone or "Europe/Paris";
    };
  };

  networking.firewall.allowedTCPPorts = [ 2283 ];
}
