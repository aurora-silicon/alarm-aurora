# Enable Aurora's Mesa (org.freedesktop.Platform.GL.aurora) for Flatpak apps
# started from a shell. Matches /usr/lib/environment.d/60-aurora-flatpak-gl.conf.
if [ -z "${FLATPAK_GL_DRIVERS-}" ]; then
    export FLATPAK_GL_DRIVERS=aurora:default:host
fi
