// SPDX-License-Identifier: MIT
// udev IMPORT{program} helper: prints AURORA_DRM_COMPUTE_ONLY=1 when the DRM node
// given as argv[1] belongs to an Asahi-uAPI driver reporting DRM_ASAHI_FEATURE_COMPUTE_ONLY.
#include <drm/drm.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define DRM_ASAHI_FEATURE_COMPUTE_ONLY (1ULL << 41)

struct asahi_get_params {
  uint32_t param_group;
  uint32_t pad;
  uint64_t pointer;
  uint64_t size;
};
#define ASAHI_IOCTL_GET_PARAMS DRM_IOW(DRM_COMMAND_BASE + 0x00, struct asahi_get_params)

int main(int argc, char **argv) {
  if (argc != 2)
    return 1;
  int fd = open(argv[1], O_RDWR | O_CLOEXEC);
  if (fd < 0)
    return 0;
  char name[32] = {0};
  struct drm_version version = {.name_len = sizeof(name) - 1, .name = name};
  // The GET_PARAMS number is driver-private: ask only the drivers serving the Asahi uAPI.
  if (ioctl(fd, DRM_IOCTL_VERSION, &version) == 0 && (!strcmp(name, "aurora") || !strcmp(name, "asahi"))) {
    uint64_t features = 0;
    struct asahi_get_params params = {.param_group = 0, .pointer = (uintptr_t)&features, .size = sizeof(features)};
    if (ioctl(fd, ASAHI_IOCTL_GET_PARAMS, &params) == 0 && (features & DRM_ASAHI_FEATURE_COMPUTE_ONLY))
      printf("AURORA_DRM_COMPUTE_ONLY=1\n");
  }
  close(fd);
  return 0;
}
