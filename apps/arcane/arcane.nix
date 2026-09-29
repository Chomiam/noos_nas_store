{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/arcane";
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/data 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.arcane = {
    image = "ghcr.io/getarcaneapp/arcane:latest";
    autoStart = true;
    ports = [ "3552:3552" ];
    volumes = [
      "/var/run/docker.sock:/var/run/docker.sock"
      "${dataDir}/data:/app/data"
    ];
    environment = {
      PORT = "3552";
      ENCRYPTION_KEY = "0c8f24b63e073f21f04431b2bd81f6f65bbf5b2571ccaf9eda3dc5eab3486f85";
    };
  };

  networking.firewall.allowedTCPPorts = [ 3552 ];
}
