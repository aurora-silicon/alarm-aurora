# Sourced after flatpak.sh (hence the name), so the x86_64 entries that start
# their app in a 4 KiB page tree come ahead of Flatpak's exports of the same
# name. Matches /usr/lib/systemd/user-environment-generators/61-aurora-flatpak-x86-exports.
case ":${XDG_DATA_DIRS-}:" in
    *:/var/lib/aurora-flatpak-gl/exports/share:*) ;;
    *) export XDG_DATA_DIRS="/var/lib/aurora-flatpak-gl/exports/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}" ;;
esac
