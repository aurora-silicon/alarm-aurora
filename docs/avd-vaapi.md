# AVD VA-API driver

`libva-v4l2-request-avd` packages commit
`4f60c51f7841dd74bb61c94a4ad31e630bbdab01` from the public
`omacom/libva-v4l2_request` `avd-fixes` branch. It installs:

```text
/usr/lib/dri/v4l2_request_drv_video.so
/usr/lib/dri/asahi_drv_video.so -> v4l2_request_drv_video.so
```

The alias makes libva's normal render-node discovery select the driver. No
global `LIBVA_DRIVER_NAME`, browser preference, firmware, permission change, or
sandbox exception is installed.

Validate the installed package with `env -u LIBVA_DRIVER_NAME vainfo --display
drm`, then compare `ffmpeg -hwaccel vaapi` frame MD5 output with software for
licensed H.264, HEVC, VP9 and AV1 clips. Run mpv muted with both `--hwdec=vaapi`
and `--hwdec=vaapi-copy`. Native Firefox must use its normal RDD sandbox;
capture `about:support` and
`MOZ_LOG=PlatformDecoderModule:5,FFmpegVideo:5`. A software fallback or sandbox
denial is not a hardware pass. Keep bounded kernel logs and repeat `vainfo`
after seek, close and reopen tests.
