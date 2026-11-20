#define _GNU_SOURCE
#include <security/pam_appl.h>
#include <security/pam_ext.h>
#include <security/pam_modules.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifdef MOCK_PASSWORD
int pam_sm_authenticate(pam_handle_t *pamh, int flags, int argc, const char **argv)
{
    char *value = NULL;
    int status = pam_prompt(pamh, PAM_PROMPT_ECHO_OFF, &value, "Password:");
    int ok = status == PAM_SUCCESS && value && strcmp(value, "test-only-password") == 0;
    free(value);
    return ok ? PAM_SUCCESS : PAM_AUTH_ERR;
}
#else
static int converse(int count, const struct pam_message **messages,
                    struct pam_response **out, void *data)
{
    struct pam_response *responses = calloc(count, sizeof(*responses));
    if (!responses) return PAM_BUF_ERR;
    for (int i = 0; i < count; i++) {
        printf("%s\n", messages[i]->msg);
        fflush(stdout);
        if (messages[i]->msg_style == PAM_PROMPT_ECHO_OFF) {
            char line[512];
            if (!fgets(line, sizeof(line), stdin)) {
                free(responses);
                return PAM_CONV_ERR;
            }
            line[strcspn(line, "\n")] = 0;
            responses[i].resp = strdup(line);
        }
    }
    *out = responses;
    return PAM_SUCCESS;
}

int main(int argc, char **argv)
{
    pam_handle_t *pamh = NULL;
    const struct pam_conv conversation = { converse, NULL };
    int status = pam_start_confdir("polkit-1", argc > 2 ? argv[2] : "test-user", &conversation, argv[1], &pamh);
    if (status == PAM_SUCCESS) {
        status = pam_authenticate(pamh, 0);
        pam_end(pamh, status);
    }
    printf("RESULT %d\n", status);
    return status;
}
#endif
