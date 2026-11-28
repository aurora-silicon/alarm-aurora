// SPDX-License-Identifier: GPL-2.0-only
#include <stdio.h>
#include <libvmaf/model.h>

int main(void)
{
    VmafModel *model = NULL;
    VmafModelConfig config = { .flags = VMAF_MODEL_FLAGS_DEFAULT };
    int err = vmaf_model_load(&model, &config, "vmaf_v0.6.1");

    if (err || !model) {
        fprintf(stderr, "built-in vmaf_v0.6.1 model load failed: %d\n", err);
        return 1;
    }

    vmaf_model_destroy(model);
    return 0;
}
