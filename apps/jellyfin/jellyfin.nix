{ config, lib, pkgs, ... }:

let
  user = config.steveos.user.username;
  dataDir = "/home/${user}/docker/jellyfin";
  mediaDir = "/home/${user}/videos";
  gpuType = config.steveos.hardware.gpu or "intel";

  # Détection automatique du GPU selon le matériel de la machine
  isNvidia = gpuType == "nvidia" || gpuType == "nvidia-legacy";
  hasDri = builtins.pathExists "/dev/dri" || gpuType == "intel" || gpuType == "amd";

  gpuOptions =
    if isNvidia then
      [ "--gpus=all" ]
    else if hasDri then
      [ "--device=/dev/dri:/dev/dri" ]
    else
      [ ];

  gpuEnv =
    if isNvidia then {
      NVIDIA_VISIBLE_DEVICES = "all";
      NVIDIA_DRIVER_CAPABILITIES = "all";
    } else { };
in
{
  systemd.tmpfiles.rules = [
    "d /home/${user}/docker 0775 ${user} users -"
    "d ${dataDir} 0775 ${user} users -"
    "d ${dataDir}/config 0775 ${user} users -"
    "d ${dataDir}/cache 0775 ${user} users -"
    "d ${mediaDir} 0775 ${user} users -"
    "d ${mediaDir}/movies 0775 ${user} users -"
    "d ${mediaDir}/tv_shows 0775 ${user} users -"
    "d ${mediaDir}/anims 0775 ${user} users -"
  ];

  virtualisation.oci-containers.backend = "docker";
  virtualisation.oci-containers.containers.jellyfin = {
    image = "lscr.io/linuxserver/jellyfin:latest";
    autoStart = true;
    ports = [
      "8096:8096"
      "8920:8920"
      "1900:1900/udp"
      "7359:7359/udp"
    ];
    volumes = [
      "${dataDir}/config:/config"
      "${dataDir}/cache:/cache"
      "${mediaDir}/movies:/data/movies"
      "${mediaDir}/tv_shows:/data/tv_shows"
      "${mediaDir}/anims:/data/anims"
      "${mediaDir}:/media"
    ];
    environment = {
      PUID = "1000";
      PGID = "100";
      TZ = config.steveos.timeZone or "Europe/Paris";
      UMASK = "002";
    } // gpuEnv;
    extraOptions = gpuOptions;
  };

  networking.firewall.allowedTCPPorts = [ 8096 8920 ];
  networking.firewall.allowedUDPPorts = [ 1900 7359 ];
}
