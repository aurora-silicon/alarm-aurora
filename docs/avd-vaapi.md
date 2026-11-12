# AVD VA-API driver

`libva-v4l2-request-avd` packages commit
`4f60c51f7841dd74bb61c94a4ad31e630bbdab01` from the public
`omacom/libva-v4l2_request` `avd-fixes` branch. It installs:

```text
/usr/lib/dri/v4l2_request_drv_video.so
/usr/lib/dri/asahi_drv_video.so -> v4l2_request_drv_video.so
/usr/lib/dri/aurora_drv_video.so -> v4l2_request_drv_video.so
```

The aliases cover the older and current render-node driver names, so libva's
normal discovery selects the driver. No global `LIBVA_DRIVER_NAME`, browser
preference, firmware, permission change, or sandbox exception is installed.

Validate the installed package with `env -u LIBVA_DRIVER_NAME vainfo --display
drm`, then compare `ffmpeg -hwaccel vaapi` frame MD5 output with software for
licensed H.264, HEVC, VP9 and AV1 clips. Run mpv muted with both `--hwdec=vaapi`
and `--hwdec=vaapi-copy`. Native Firefox must use its normal RDD sandbox;
capture `about:support` and
`MOZ_LOG=PlatformDecoderModule:5,FFmpegVideo:5`. A software fallback or sandbox
denial is not a hardware pass. Keep bounded kernel logs and repeat `vainfo`
after seek, close and reopen tests.

## Firefox

Firefox's RDD sandbox does not admit the media controller node and the four
media/request ioctls that libva-v4l2-request needs, and it rejects `sysinfo`,
without which Mesa's zink driver cannot create the GBM device behind VA-API
DMABuf surfaces, so stock Firefox decodes in software. `packages/firefox` is
Arch Linux ARM's `extra/firefox` recipe with `rdd-v4l2-request.patch` (Mozilla
bug 2080696 plus the RDD `sysinfo` patch), imported by
`scripts/import-alarm-firefox.py`; its `pkgrel` gets a `.2` so it replaces
ALARM's build. The build carries no Google API key (Arch's is for Arch Linux
only). The recipe is marked `# aurora-builder: heavy`: it builds only when a
manual `packages.yml` run names it. `.github/workflows/track-firefox.yml`
imports ALARM's newest recipe every two hours, builds it on a proposal branch
and merges it once the build passed (`TRACK_FIREFOX=false` /
`AUTO_MERGE_FIREFOX=false` turn that off).
